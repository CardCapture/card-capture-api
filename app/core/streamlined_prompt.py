"""
Streamlined vision-first prompt used by the Gemini-only extraction path.

The prompt asks Gemini 2.5 Flash to (1) READ each field literally,
(2) INTERPRET using common-sense reasoning, (3) CROSS-CHECK against other
fields, (4) apply field-specific rules, and (5) REPORT using the same
JSON output shape that parse_gemini_quality_response expects.

Two additions beyond the original bakeoff prompt, both folded into the same
single call so they cost no extra latency:

- ORIENTATION: the model reports how many degrees the image must rotate to be
  upright (_meta.image_rotation_degrees). This replaces the rotation correction
  that the DocAI Enterprise OCR processor used to provide.
- DISCOVERY: the model is allowed to return clearly-labeled fields it sees on
  the card that are not in the configured field list. Downstream code captures
  these as suggestions so a custom card format can be onboarded without
  pre-configuring every field.
"""
import json
from typing import List


STREAMLINED_PROMPT_TEMPLATE = """
You are an experienced reader of handwritten student inquiry cards.

Your job: for every field below, produce the best-judgment value by looking at
the image, reasoning about what was written, and sanity-checking the result.

Fields to extract (output one entry per field, in this order):
{field_list}

Valid majors (for the mapped_major field):
{valid_majors_json}

----------------------------------------------------------------
STEP 0 - ORIENTATION (do this first and get it exactly right).
Decide how many degrees the image must be rotated CLOCKWISE so the card reads
normally: upright, text running left-to-right, with the printed header/logo at
the top. The only valid answers are 0, 90, 180, or 270.

Reason it out explicitly before committing to a value:
- Pick a reliable anchor that is PRINTED on the card (not handwritten): the
  school name or logo, the card's printed title, or the printed field labels
  (for example "Legal name", "Address", "Email", "High school"). These are
  always designed to sit at the top and read left-to-right.
- If that printed text already reads normally left-to-right, the answer is 0.
- If the printed text runs bottom-to-top up the LEFT edge (rotated counter-
  clockwise), it needs 90 clockwise.
- If it runs top-to-bottom down the RIGHT edge (rotated clockwise), it needs
  270 clockwise.
- If the printed text is upside down (anchor at the bottom, letters inverted),
  it needs 180.

Guard against the two common mistakes:
- Do NOT confuse upright with upside down. Upright text reads left-to-right and
  the letters are not inverted; if you would have to read the labels upside
  down, the answer is 180, not 0.
- When choosing between 90 and 270, pick the one that makes the PRINTED labels
  read left-to-right. Getting this backwards leaves the card upside down.

Report the value once in the _meta block described in STEP 5. Read all fields
as if the card were already upright.

----------------------------------------------------------------
WORKFLOW - do this for every field:

STEP 1 - READ.
Look at the field's box on the card. Transcribe what the letters / digits
literally look like. Capture this as original_value. If the box is blank,
value and original_value are both empty string.

STEP 2 - INTERPRET.
Apply common-sense reasoning to clean up what you read:
- Names: prefer plausible human names. If the literal letters give an
  implausible string starting with "Nc...", "Xc...", "Wr...", it is almost
  certainly a faintly-written "Mc...", "Mac...", "O'...", "De...", "La...",
  "Van...". Look again for a faint prefix letter. Common surname prefixes to
  watch for: Mc, Mac, De La, Van, O', La, Von.
  DO NOT change a clearly-written unusual name to a common one. Unusual names
  are fine when the letters actually support them.
- Emails: the domain must look like a real domain. Fix obvious character
  confusions (l vs 1, o vs 0, O vs 0). Known domains in this dataset include
  gmail.com, yahoo.com, icloud.com, wyliebulldogs.org, abileneisd.org, mcm.edu.
- Phone: US format XXX-XXX-XXXX. Pay extra attention to confusable digit pairs
  (4/9, 7/1, 8/3, 5/6, 0/6). If the area code does not plausibly match the
  city / state you read for this student, re-examine the digits.
- Addresses: the house number can appear BEFORE the street name (standard)
  OR AFTER it (common on these cards when the student ran out of room).
  Example: an address box reading "Sierra Sunset 2091" means house number
  2091 on Sierra Sunset, and should be output as "2091 Sierra Sunset".
  ALWAYS scan the entire address area for digits and put them at the start
  of the output value. NEVER drop a visible number just because it appears
  in an unusual position.
  Expand "St" to "Street" only if other examples on the card do, otherwise
  preserve as-written.
- Schools: expand "HS" to "High School", "JH" or "Jr High" to "Junior High",
  "MS" or "Middle" to "Middle School".
- Dates: MM/DD/YYYY. For entry_term, include season: "Fall 2025", "Spring 2026".
  Default to Fall if only a year is written.
- GPA: decimal (e.g., 3.6). Rank: preserve as "X of Y".
- Major: preserve the exact text written on the card. Do not clean up typos
  in the major itself (that is what mapped_major is for).

STEP 3 - CROSS-CHECK (before finalizing any field).
If multiple fields are present, verify they agree:
- city / state / zip: Abilene TX should have zip starting 795-796. Cedar Hill
  TX zips start 751. If they do not agree, re-examine the least-legible one.
- area code vs region: 325 = Abilene TX area; 214/469/972 = Dallas area;
  940 = north TX. If phone area code does not match city, re-examine the phone.
- email vs name: student's email name usually contains part of their name or
  a school-assigned ID. If the email name looks nothing like the name, double
  check both.
- If cross-check fails, trust whichever field is more legibly written and
  revise the less-legible one toward consistency.

STEP 4 - EXTRA RULES FOR SPECIFIC FIELDS.

first_name / last_name: split the student's name. If the card has a single
"NAME" box with "Jane Doe", first_name="Jane" and last_name="Doe". If the card
has separate first/last boxes, use those directly. Hyphenated and compound
surnames (McCabe-Davis, De La Torre, Van Der Berg) stay whole in last_name.

preferred_first_name: this field is a NICKNAME and frequently differs from
first_name on purpose (e.g., legal name "Robert", preferred "Bobby"; legal
"Dayra", preferred "Daylen"). When first_name and preferred_first_name are
clearly different on the card, REPORT THEM AS DIFFERENT. Do NOT harmonize
them. Do NOT change first_name to match preferred_first_name. Do NOT copy
first_name into preferred_first_name. Only leave preferred_first_name blank
if the preferred box is actually empty on the card.

permission_to_text: can be a Yes/No checkbox pair OR a single opt-out checkbox.
- Yes/No pair: value is whichever is checked.
- Single opt-out with language like "don't want" or "do not want" or "opt out":
  checked = "No", blank = "Yes".
Field type: "select", detected_options: ["Yes", "No"].

student_type: look for checkbox(es) marking Freshman / Sophomore / Junior /
Senior / Graduate / Transfer. Value is whichever is VISUALLY CHECKED on the
card. If none is checked, leave blank.

CHECKBOX TRUST RULE (applies to student_type, permission_to_text, and any
other select/checkbox field): the value is whichever option is visually
marked. DO NOT override a checkbox mark based on other fields on the card
or based on what you think would be more plausible for this student.

PREFER A MARK OVER BLANK: if any option in the checkbox group shows ANY
visible mark (even a very faint dot, partial fill, check, cross, or
scribble), output that option rather than leaving the field blank. These
fields are usually required for the card to be useful, so a faint mark is
far more likely to be a real selection than an accident. Only output blank
when the entire checkbox group appears genuinely empty with zero marks
anywhere. When picking between a faint mark and blank, always pick the
marked option and set certainty="mostly_certain" or "uncertain" as
appropriate.

major: EXACT text from the card, including any typos. Do not clean up.
Field type: "text".

mapped_major: use the valid_majors list above. Pick the closest match to the
major the student wrote. Use intelligent matching ("business" -> "Business
Administration | BSBA"; "teacher" or "education" -> "Education"; "medical" or
"pre-med" -> "Biology" or "Chemistry" or similar; "psych" -> "Psychology").
The pipe character "|" in major names is part of the name, not a separator.
If no reasonable match, output "Undecided".
Field type: "select", detected_options should list the full valid_majors list.

ADDITIONAL FIELDS (discovery) - CRITICAL: never drop information a student wrote.
The card may have clearly-labeled fields that are NOT in the list above. Common
example: a "Cell phone" line that is separate from "Home phone", or an intended
sport, campus visit date, counselor name, parent name.

You MUST output EVERY labeled field that has a written value or a visible
checkbox mark, even when that label is not in the list above. Derive a
snake_case key from the printed label ("Cell phone" -> cell_phone, "Parent
name" -> parent_name) and use the same output shape as every other field.
Treat each distinct printed label as its own field: if the card shows both
"Home phone" and "Cell phone", output BOTH (home phone from the home phone
line, cell phone from the cell phone line). Do NOT merge a value written on one
labeled line into a different field.

Omitting a value the student actually wrote - a phone number, email, name, or
any filled field - is a serious error. When a labeled field clearly has a
value, ALWAYS include it.

Limits: only treat printed FORM LABELS that have a fill-in area as fields.
Ignore instructional sentences, marketing copy, and the school's address/phone
in the card's footer. Do NOT invent fields and do NOT add a labeled field that
is blank.

STEP 5 - REPORT.
Begin your JSON object with a "_meta" key carrying the orientation, then one
entry per field. The _meta block uses this exact shape:
{{
  "_meta": {{
    "image_rotation_degrees": 0
  }}
}}

For each field, output JSON matching this shape exactly:
{{
  "field_name": {{
    "value": "<final value>",
    "edit_made": true/false,
    "edit_type": "none|format_correction|ocr_correction|typo_fix|plausibility_fix|cross_validation_fix|mapped_value|missing_data|unclear_text",
    "original_value": "<what the letters literally looked like before any interpretation>",
    "text_clarity": "clear|mostly_clear|unclear|unreadable",
    "certainty": "certain|mostly_certain|uncertain",
    "notes": "<brief reviewer note, 1 short sentence, human-style, no AI/OCR/system references>",
    "field_type": "text|select|checkbox|email|phone|date",
    "detected_options": ["option1", ...]
  }}
}}

edit_type guidance:
- none: no change from the literal reading
- format_correction: only formatting changed (case, spacing, phone format)
- typo_fix: fixed obvious misspelling from OCR-like confusion
- plausibility_fix: adjusted toward a more plausible reading (faint prefix,
  confusable letter) based on reviewer reasoning
- cross_validation_fix: revised based on cross-check with another field
- mapped_value: only used for mapped_major
- missing_data: field is blank on the card
- unclear_text: too illegible to commit to a value

Certainty rules:
- "certain" only if you would bet money on this reading after the cross-check
- "mostly_certain" if confident but there is some ambiguity
- "uncertain" if the handwriting is genuinely hard to read

Output rules:
- Output the _meta block first, then ALL fields listed above, even blanks.
- Respond with ONLY the JSON object. No markdown fences, no preamble.
"""


def _build_field_list(card_fields: List[dict]) -> str:
    lines = []
    for f in card_fields or []:
        if not isinstance(f, dict) or not f.get("enabled", True):
            continue
        key = f.get("key") or f.get("name") or f.get("field_name")
        if not key:
            continue
        req = " (required)" if f.get("required") else ""
        ftype = f.get("field_type") or "text"
        lines.append(f"  - {key} [{ftype}]{req}")
    if not any("mapped_major" in ln for ln in lines):
        lines.append("  - mapped_major [select]")
    return "\n".join(lines)


def render_streamlined_prompt(card_fields: List[dict], valid_majors: List[str]) -> str:
    field_list = _build_field_list(card_fields)
    majors_json = json.dumps(valid_majors or [], indent=2).replace("{", "{{").replace("}", "}}")
    return STREAMLINED_PROMPT_TEMPLATE.format(
        field_list=field_list,
        valid_majors_json=majors_json,
    )
