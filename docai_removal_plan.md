# DocAI Removal Plan

**Status:** Ready to implement. Bakeoff complete, decisions made, prompt drafted.
**Author context:** Plan written after a four-round model bakeoff comparing DocAI+Gemini vs multiple vision-only variants on real McMurry cards.
**Audience:** An agent (or engineer) picking this up cold to execute the migration.

---

## Read this first

The current production card-processing pipeline uses Google Document AI (a custom processor trained on McMurry's card, id `894b9758c2215ed6`) to extract fields, crops the image, then passes the crop + DocAI field values to Gemini 2.5 Flash for correction and quality scoring.

A head-to-head bakeoff compared this baseline against five vision-only alternatives on real McMurry cards. Key findings:

1. **Gemini 2.5 Flash vision-only is faster and at least as accurate.** On 10 McMurry cards, it was ~6.8s faster per card (median 20.5s → 13.7s, a 33% reduction) and more often corrected OCR-style typos (Buisness→Business, Martiner→Martinez, Sciequa→Science) that the DocAI path was preserving.

2. **A streamlined prompt with an explicit reviewer pass beats the current prompt.** On 5 cards, the new prompt added 12 correct improvements (state inferred from city/zip, domain typos fixed, short years expanded, city names normalized) against 4 regressions. All 4 regressions were patched with targeted rules (preferred-name distinction, checkbox-trust "prefer mark over blank", address house-number example).

3. **Claude Haiku 4.5 was materially worse on handwriting.** Do not use it for this task. Claude Sonnet 4.6 matched baseline accuracy but was 2x slower than Gemini Flash. Gemini Pro added latency and forced thinking mode with no accuracy gain. Flash-Lite was fast but emitted a wrapped JSON envelope that broke parsing.

**Decision:** migrate to Gemini 2.5 Flash vision-only using the streamlined prompt included in full in Appendix A below. Ship behind a per-school feature flag. Keep DocAI code paths intact for rollback. After a successful two-week shadow + staged rollout, delete the DocAI integration.

The full prompt (Appendix A) and a reference Gemini call implementation (Appendix B) are inlined at the end of this document so this plan is self-contained.

---

## Your task

Implement the DocAI-removal migration in `card-capture-api` with a per-school feature flag and a shadow-mode comparison period, so the team can flip a flag per school (starting with McMurry) and verify field-level accuracy against the current pipeline before deleting DocAI.

You are not redesigning. You are implementing the plan below. Deviate only on clear improvements, and confirm deviations with the user before committing.

---

## Ground rules

- Work on a feature branch off `staging`. Do not merge to `staging` without the user's explicit go-ahead.
- Never commit the DocAI deletion until after the shadow-mode period and rollout. Keep all existing DocAI code paths intact behind the flag.
- No backwards-compatibility shims are needed for the *new* code path. The flag is the switch; when off, the old path runs exactly as today.
- Follow the existing code style in the repo (Ruff, 120-char lines, Python 3.9 type hints).
- Read `CLAUDE.md` at the repo root before starting.

---

## Reference: files the bakeoff touched and what they contain

| File | What matters |
|------|--------------|
| `app/pipeline/pipeline.py:155-265` (`_extract`) | Current extraction stage. DocAI → Gemini sequence lives here. Flag check goes here. |
| `app/services/docai_service.py:55` (`process_image_with_docai`) | Calls DocAI custom processor, crops image, returns `(fields, cropped_image_path, ocr_text, serial_number)`. Leave untouched. |
| `app/services/gemini_service.py:16` (`process_card_with_gemini_v2`) | Current Gemini call. Takes a cropped image + DocAI field dict + valid_majors. Leave untouched. |
| `app/services/gemini_service.py:275` (`parse_gemini_quality_response`) | Parses Gemini JSON into the FieldData shape the pipeline expects. **Reuse this unchanged** for the new path — the streamlined prompt preserves the same output schema specifically so this keeps working. |
| `app/core/gemini_prompt.py` | Current prompt. Leave untouched; create a sibling file for the streamlined prompt. |
| `app/config.py:12` (`DOCAI_PROCESSOR_ID`), `app/config.py:71` (`GEMINI_MODEL`) | Existing config. Add new config keys alongside. |
| `supabase/migrations/` | Migrations live here. You will add one new column to `schools`. |
| Appendix A (below) | The winning streamlined prompt (already patched with preferred-name, checkbox-trust, and house-number rules). Source of truth for what to build into `app/core/streamlined_prompt.py`. |
| Appendix B (below) | Reference implementation of the Gemini vision-only call using the streamlined prompt. Mirror this when writing the service. |

---

## Implementation steps

### Step 1: Create `app/core/streamlined_prompt.py`

Build the new prompt module using the full content in **Appendix A** as your source of truth.

- Module name: `app/core/streamlined_prompt.py`.
- Public API: `render_streamlined_prompt(card_fields: list[dict], valid_majors: list[str]) -> str`.
- Internal helper: `_build_field_list(card_fields)` (prefix with `_`).
- The prompt template is a large triple-quoted string constant. Preserve every rule in Appendix A exactly; they were each added in response to observed failures during the bakeoff.

### Step 2: Create `app/services/gemini_vision_service.py`

New module, mirrors `gemini_service.py` structure but simpler:

```python
def process_card_with_gemini_vision(
    image_path: str,
    card_fields: list[dict],
    valid_majors: list[str],
) -> dict:
    """
    Vision-only extraction: sends the raw card image + streamlined prompt
    to Gemini 2.5 Flash, returns the same field dict shape that
    process_card_with_gemini_v2 produces so downstream code is unaffected.
    """
```

- Load the client via `app.core.clients.get_gemini_client` (same helper the existing service uses).
- Build the prompt with `render_streamlined_prompt(card_fields, valid_majors)`.
- Use `thinking_config={"thinking_budget": 0}` in `GenerateContentConfig` — the bakeoff confirmed thinking adds latency without improving accuracy on this task.
- Wrap the generate_content call in `retry_with_exponential_backoff` (same pattern as `gemini_service.py:157`).
- After parsing, call `parse_gemini_quality_response(response.text, placeholder_fields)` from the existing gemini_service where `placeholder_fields` is an empty-field dict built from `card_fields` (mirrors `build_empty_docai_fields` in the experiments folder). This gets you the same output shape as the current path for free.
- Capture Sentry errors the same way the existing service does.

Reference implementation: **Appendix B** at the end of this document. That reference is a simpler one-shot call without retry or Sentry; your production service must add both (same retry pattern as `app/services/gemini_service.py:157`, same Sentry capture as `gemini_service.py:271`).

### Step 3: Add config keys

In `app/config.py`:

```python
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
VISION_ONLY_EXTRACTION_DEFAULT = os.getenv("VISION_ONLY_EXTRACTION_DEFAULT", "false").lower() == "true"
```

Rationale: model choice may diverge from the current `GEMINI_MODEL` (e.g., if we later A/B a different Flash variant for the new path). The default flag lets staging turn the new path on globally without a DB migration.

### Step 4: Add per-school feature flag (DB migration)

New migration file (`supabase/migrations/<timestamp>_add_vision_only_extraction.sql`):

```sql
ALTER TABLE schools
ADD COLUMN use_vision_only_extraction boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN schools.use_vision_only_extraction IS
  'When true, extraction pipeline skips DocAI and uses Gemini vision with the streamlined prompt. See docai_removal_plan.md.';
```

Confirm with the user before running `db-migrate.sh` on staging. **Never** run on production until explicitly approved.

### Step 5: Wire the flag into `pipeline.py`

Modify `_extract()` in `app/pipeline/pipeline.py` (around line 155). At the top of the method:

```python
from app.config import VISION_ONLY_EXTRACTION_DEFAULT
from app.services.gemini_vision_service import process_card_with_gemini_vision

supabase = get_supabase_client()
school_query = (
    supabase.table("schools")
    .select("docai_processor_id, use_vision_only_extraction")
    .eq("id", context.school_id)
    .maybe_single()
    .execute()
)
school_row = school_query.data or {}
use_vision_only = school_row.get("use_vision_only_extraction", VISION_ONLY_EXTRACTION_DEFAULT)

if use_vision_only:
    return self._extract_vision_only(image_path, context)
# else fall through to existing DocAI+Gemini path unchanged
```

Add a new method `_extract_vision_only(self, image_path, context) -> ProcessingResult` that:

1. Calls `process_card_with_gemini_vision(image_path, context.card_fields, context.valid_majors)`.
2. Converts the returned field dict to `FieldData` objects (same pattern as lines 219-243 in the existing `_extract`).
3. Returns a `ProcessingResult` with `stage=ProcessingStage.EXTRACTION` and metadata noting `"extraction_mode": "vision_only"`.

**Important:** the existing `_extract` reads `card_fields` from a `context.card_fields` attribute — verify this exists on `PipelineContext`. If not, thread it through from `execute()` / `_initialize_pipeline_context()`.

### Step 6: Serial number decision

The current DocAI path extracts a serial number and short-circuits to an existing-student lookup, skipping Gemini entirely for repeat cards (`pipeline.py:179-194`). This saves ~$0.003 and ~10s per repeat scan.

**Options:**

- **A (recommended for v1):** drop the optimization. The streamlined prompt output has no serial_number field by default. Repeat cards pay full Gemini cost.
- **B (later):** add `serial_number` to the prompt's field list so Gemini extracts it, then add the existing-student short-circuit check between extraction and enhancement. Requires no DocAI.

Start with A to ship simple. Open a follow-up ticket for B if usage data shows the short-circuit was load-bearing.

**Confirm the choice with the user before coding.**

### Step 7: Shadow mode (strongly recommended, optional)

Before flipping the flag per school, add a side-by-side comparison:

1. New table `extraction_shadow_runs` with columns: `id uuid, job_id uuid, image_path text, primary_fields jsonb, shadow_fields jsonb, primary_latency_s numeric, shadow_latency_s numeric, created_at timestamptz default now(), school_id uuid`.
2. Env flag `SHADOW_VISION_EXTRACTION=true`. When on, the worker runs the current DocAI+Gemini path (primary, used for the DB) AND the vision-only path (shadow, only logged). Both results land in `extraction_shadow_runs`.
3. Run shadow mode on staging for 3-5 days against real uploads. Aim for 100+ shadow rows.
4. Write a quick analysis script in `experiments/model_bakeoff/` that loads shadow rows and computes per-field disagreement rates.

If your time budget is tight, skip shadow mode and go straight to per-school flag flip with manual review of the first ~20 scans. The user is comfortable with that path as a fallback.

### Step 8: Tests

Add `tests/unit/test_gemini_vision_service.py`:

- Unit test that mocks `get_gemini_client` and verifies `process_card_with_gemini_vision` calls `generate_content` with the streamlined prompt and the image bytes.
- Integration test marker (`@pytest.mark.integration`) that runs the real call against a sample image checked into `tests/fixtures/`. Skip by default in CI.

Add a pytest for the pipeline flag branching:

- Test that when `use_vision_only_extraction=True`, `process_image_with_docai` is NOT called and `process_card_with_gemini_vision` IS called.
- Test that when the flag is False, current behavior is preserved.

### Step 9: Staging deploy

1. Merge to `staging` via `git merge feat/vision-only-extraction --no-edit && git push origin staging` (user preference per CLAUDE.md memory: no PRs for staging).
2. Cloud Build will deploy automatically.
3. Run the migration on staging via `./db-migrate.sh`.
4. Smoke test: upload a card via the frontend against staging, confirm it processes. Check Sentry for errors.

### Step 10: Enable for McMurry on staging

```sql
UPDATE schools SET use_vision_only_extraction = true WHERE id = 'b1a2c3d4-e5f6-7890-1234-56789abcdef0';
```

(McMurry's school_id, confirmed during the bakeoff.)

Upload 5-10 real cards against McMurry on staging. Inspect the resulting `student_school_interactions` rows. Compare field accuracy to expectations. If clean, move to prod.

### Step 11: Production rollout

1. Run the migration on prod DB.
2. Enable the flag for one or two low-volume pilot schools first (ask the user which). Monitor for a week.
3. Expand to all schools after clean pilot. Keep the flag column so it can be flipped off per school if issues arise.

### Step 12: DocAI deletion (later, separate PR)

After 2-3 weeks of stable production operation with all schools on vision-only:

1. Delete `app/services/docai_service.py`.
2. Delete the DocAI branch in `_extract` (keeping only `_extract_vision_only` renamed back to `_extract`).
3. Drop the `docai_processor_id` column from `schools` in a new migration.
4. Remove `google-cloud-documentai` from `requirements.txt`.
5. Remove DocAI env vars from `.env.example` and deployment configs.
6. Delete the feature flag column (optional; could also keep it as a kill switch).

**Do not do Step 12 until the user explicitly approves.** It is the point of no return.

---

## Acceptance criteria

- [ ] `use_vision_only_extraction` column exists in staging and prod.
- [ ] With the flag off (all existing schools), production behavior is bit-for-bit unchanged. Existing tests still pass.
- [ ] With the flag on for a school, scans for that school skip DocAI, call Gemini vision with the streamlined prompt, and populate `student_school_interactions` / `reviewed_data` with the same field schema as before.
- [ ] Latency on flagged scans is meaningfully lower than unflagged (expect ~30% reduction based on bakeoff).
- [ ] No Sentry errors introduced in the new code path.
- [ ] Unit tests cover both branches of `_extract`.
- [ ] Shadow mode rows exist for at least 100 real uploads before flipping a school to primary (if shadow mode is implemented).

---

## Things to confirm with the user before starting

1. **Serial number handling.** Drop the short-circuit (Option A, recommended) or preserve it via prompt-based extraction (Option B)?
2. **Shadow mode.** Implement it or skip it in favor of a careful manual rollout?
3. **Which schools to pilot first** after McMurry on staging?
4. **Flag default.** Should `VISION_ONLY_EXTRACTION_DEFAULT` be `false` (safe) or `true` on staging?
5. **Enhancers.** The current `FieldSplitterEnhancer` is now partially redundant since the streamlined prompt outputs split fields. Leave it running (no-op for already-split fields) or remove? Recommend leaving for safety.

---

## If you hit trouble

- **Gemini returns wrapped JSON (`{"fields": {...}}`) instead of the flat schema:** the streamlined prompt asks for flat output but Gemini sometimes wraps anyway. Add the safety-net normalization helper below into the service:

  ```python
  def _normalize_fields(raw: dict) -> dict:
      """Unwrap a {'fields': {...}} envelope if the model wrapped its output."""
      if not isinstance(raw, dict):
          return {}
      if (
          "fields" in raw
          and isinstance(raw["fields"], dict)
          and any(
              isinstance(v, dict) and ("value" in v or "field_type" in v)
              for v in raw["fields"].values()
          )
      ):
          return raw["fields"]
      return raw
  ```

- **Fields missing that DocAI always provided:** the streamlined prompt lists fields from the school's `card_fields` config, not from the DocAI processor schema. If a school's config is incomplete, the prompt will skip those fields. Audit `schools.card_fields` for the pilot school before flipping.
- **Latency looks the same, not faster:** check that the new path is actually being taken (log `extraction_mode` in the worker). If it is, check the region of your Vertex / Gemini endpoint matches your Cloud Run region.
- **Checkbox fields still blanking despite prompt:** that issue was mitigated with the checkbox "prefer a mark over blank" rule (see Appendix A), but not fully eliminated. The field's `requires_human_review` flag should catch it. If you see frequent blanking in shadow mode, escalate to the user before rolling out.

---

## Appendix A: The streamlined prompt (full content)

Build `app/core/streamlined_prompt.py` from this. The template is a module-level string constant; the two helpers below it are small render utilities.

```python
"""
Streamlined vision-first prompt used by the Gemini-only extraction path.

The prompt asks Gemini 2.5 Flash to (1) READ each field literally,
(2) INTERPRET using common-sense reasoning, (3) CROSS-CHECK against other
fields, (4) apply field-specific rules, and (5) REPORT using the same
JSON output shape that parse_gemini_quality_response expects.
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
WORKFLOW — do this for every field:

STEP 1 — READ.
Look at the field's box on the card. Transcribe what the letters / digits
literally look like. Capture this as original_value. If the box is blank,
value and original_value are both empty string.

STEP 2 — INTERPRET.
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

STEP 3 — CROSS-CHECK (before finalizing any field).
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

STEP 4 — EXTRA RULES FOR SPECIFIC FIELDS.

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

STEP 5 — REPORT.
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
- Output ALL fields listed above, even blanks.
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
```

### Why each rule is in the prompt

Do not remove any of these without re-testing. Each was added in direct response to an observed failure in the bakeoff:

- **READ / INTERPRET / CROSS-CHECK workflow**: adds an explicit reviewer pass. Without it, Gemini did one-shot transcription and missed obvious fixes (e.g., output `ecrouch@wyliebubulldogs.org` with the doubled "bu" instead of catching the typo).
- **Name prefix hint** (Mc, Mac, De La, etc.): without this, Gemini output `Ncabe-Davis` for a card that said `McCabe-Davis` because the faint "M" was easy to miss.
- **Email known-domains list**: helps Gemini resolve ambiguous domain letters (`.ore` → `.org`, `Bmgll.com` → `gmail.com`).
- **House number example** (`Sierra Sunset 2091` → `2091 Sierra Sunset`): Gemini was dropping the house number on cards where students wrote the number after the street name. A concrete example in the prompt fixed this; generic instructions did not.
- **preferred_first_name distinction**: without this, Gemini's cross-check was over-eagerly harmonizing first_name and preferred_first_name, erasing legitimate nickname differences (`Dayra` / `Daylen`).
- **CHECKBOX TRUST + PREFER A MARK OVER BLANK**: Gemini was leaving student_type blank on cards that clearly had a marked checkbox. The trust rule alone did not fully fix this; the "prefer a mark over blank" escalation was needed to close the last regression.
- **Output schema exactly matches the existing `parse_gemini_quality_response`**: so downstream code keeps working with no changes.

---

## Appendix B: Reference Gemini vision call

Use this as the skeleton for `app/services/gemini_vision_service.py`. It does NOT include retry, Sentry, logging, or the response-schema normalization; add those for production, mirroring the patterns in `app/services/gemini_service.py`.

```python
import json
import mimetypes
import os
from typing import Any, Dict, List

from app.core.clients import get_gemini_client
from app.core.streamlined_prompt import render_streamlined_prompt
from google.genai import types as genai_types


def _mime_for(path: str) -> str:
    m, _ = mimetypes.guess_type(path)
    if m:
        return m
    ext = os.path.splitext(path)[1].lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def process_card_with_gemini_vision(
    image_path: str,
    card_fields: List[dict],
    valid_majors: List[str],
    model: str = "gemini-2.5-flash",
) -> Dict[str, Any]:
    """
    Vision-only card extraction. Sends the raw card image + streamlined
    prompt to Gemini and returns the parsed field dict.

    Output shape matches what process_card_with_gemini_v2 produces, so the
    existing parse_gemini_quality_response and downstream FieldData
    conversion in pipeline._extract continue to work unchanged.
    """
    client = get_gemini_client()
    prompt = render_streamlined_prompt(card_fields, valid_majors)

    with open(image_path, "rb") as f:
        image_data = f.read()

    response = client.models.generate_content(
        model=model,
        contents=[
            prompt,
            genai_types.Part.from_bytes(
                data=image_data,
                mime_type=_mime_for(image_path),
            ),
        ],
        config=genai_types.GenerateContentConfig(
            thinking_config={"thinking_budget": 0},
        ),
    )

    raw = response.text or ""
    try:
        parsed = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned non-JSON response: {e}") from e

    # Safety net: unwrap {"fields": {...}} if the model wraps its output
    if (
        "fields" in parsed
        and isinstance(parsed["fields"], dict)
        and any(
            isinstance(v, dict) and ("value" in v or "field_type" in v)
            for v in parsed["fields"].values()
        )
    ):
        parsed = parsed["fields"]

    return parsed
```

**Production additions required beyond this skeleton:**

1. Wrap `generate_content` in `retry_with_exponential_backoff` from `app.utils.retry_utils` (same pattern as `gemini_service.py:157-169`).
2. Add `sentry_sdk.capture_exception(e)` on errors, matching `gemini_service.py:271`.
3. Pass the parsed dict through the existing `parse_gemini_quality_response` from `gemini_service.py` so the output includes `review_confidence` and `requires_human_review`. You will need to construct a placeholder "empty docai_fields" dict to satisfy that function's signature (one empty entry per enabled field in `card_fields`).
4. Structured debug logging using `log_debug(..., service="gemini_vision")` to match existing patterns.
