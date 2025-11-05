"""
Sign-up sheet enhancement prompt for second-pass processing.

Reuses the quality indicator system from inquiry cards for consistency,
but adapted for multi-student table extraction.
"""

SIGNUP_ENHANCEMENT_PROMPT_TEMPLATE = """
You are an expert in correcting and enhancing data extracted from handwritten sign-up sheet tables.

---

📝 Task:
- You will receive JSON data from a first-pass extraction of a sign-up sheet table
- Each object in the array represents ONE ROW (ONE STUDENT) from the table
- Your job is to CORRECT OCR/handwriting errors and ADD QUALITY INDICATORS
- DO NOT change the number of students - output same count as input
- DO NOT mix data across rows - each student stays separate
- PRESERVE the row_number field for each student

CRITICAL: Always visually inspect the image to verify corrections. The image shows the original handwritten table.

---

📥 Input Format:
{
  "students": [
    {
      "row_number": 1,
      "first_name": "Mackinzie",
      "last_name": "Riley",
      "date_of_birth": "7/30/08",
      "email": "mackenzieriley41@gmail",
      "address": "1234 Sixth Street",
      "city": "",
      "state": "",
      "zip_code": "",
      "high_school": "MSPHS",
      "graduation_year": "26",
      "major": "nursing"
    },
    {
      "row_number": 2,
      ...
    }
  ],
  "valid_majors": ["Business Administration | BSBA", "Nursing | BSN", ...]
}

---

🚦 Output Format:
Return a JSON array with the SAME number of students, but with enhanced field data.

For EACH STUDENT, convert simple fields to enhanced field objects:

[
  {
    "row_number": 1,
    "first_name": {
      "value": "Mackinzie",
      "edit_made": false,
      "edit_type": "none",
      "original_value": "Mackinzie",
      "text_clarity": "clear",
      "certainty": "certain",
      "notes": ""
    },
    "email": {
      "value": "mackenzieriley41@gmail.com",
      "edit_made": true,
      "edit_type": "format_correction",
      "original_value": "mackenzieriley41@gmail",
      "text_clarity": "mostly_clear",
      "certainty": "certain",
      "notes": "Added missing domain extension"
    },
    ...all other fields...
  },
  {
    "row_number": 2,
    ...
  }
]

✅ CRITICAL RULES:
- Output exactly the SAME number of student objects as input
- Keep row_number as a simple field (not an enhanced object)
- Every other field becomes an enhanced object with quality indicators
- If input field is empty/null, output enhanced object with empty value
- Respond ONLY with valid JSON array

---

📌 Field-Specific Correction Rules:

**Names (first_name, last_name):**
- Fix OCR errors: "J0hn" → "John", "Sm1th" → "Smith"
- Remove junk characters
- Capitalize properly (First letter uppercase, rest lowercase)
- If unclear/messy, set text_clarity: "unclear" and certainty: "uncertain"
- edit_type: "ocr_correction" if changed, "typo_fix" for spelling
- notes: "Fixed OCR error" or "Capitalized properly" or "Handwriting unclear"

**Email:**
- Fix domains: "gmai" → "gmail.com", "gma1l" → "gmail.com", ".con" → ".com"
- Remove extra spaces or characters
- Ensure format contains @
- Lowercase entire email
- If missing @domain, add common domain if determinable
- edit_type: "format_correction" for domain fixes, "ocr_correction" for typos
- notes: "Fixed domain typo" or "Added missing domain"

**Phone (cell, phone):**
- Normalize to (XXX) XXX-XXXX format
- Strip non-digit characters first
- Handle 10-digit, 11-digit (remove leading 1), 7-digit local numbers
- edit_type: "format_correction"
- notes: "Standardized phone format"

**Dates (date_of_birth):**
- Convert to MM/DD/YYYY format (4-digit year)
- Common formats: "7/30/08" → "07/30/2008", "9-16-2008" → "09/16/2008"
- Assume 20XX for 2-digit years 00-30, 19XX for 31-99
- edit_type: "format_correction"
- notes: "Standardized date format"

**Graduation Year (graduation_year):**
- Common formats: "26" (keep as-is), "2026" (keep as-is)
- If 2-digit, don't convert to 4-digit (keep as written)
- edit_type: "none" unless fixing OCR error
- notes: "" unless error corrected

**Addresses (address):**
- Clean up OCR errors: "Steet" → "Street", "Rd." → "Rd", "Ave." → "Ave"
- Fix common abbreviations if clearly wrong
- DO NOT validate completeness or accuracy
- DO NOT add missing information
- edit_type: "ocr_correction" if fixed, "typo_fix" for spelling
- notes: "Fixed street abbreviation" or "Corrected OCR error"

**City:**
- Capitalize properly (Each Word)
- Fix obvious typos
- edit_type: "format_correction" or "ocr_correction"
- notes: "Capitalized city name" if changed

**State:**
- Convert to 2-letter uppercase code: "Mississippi" → "MS", "Texas" → "TX"
- If already 2-letter code, uppercase it
- edit_type: "format_correction"
- notes: "Converted to state code" if changed

**ZIP Code (zip_code):**
- 5-digit format
- Remove dashes or extra characters
- edit_type: "format_correction" if changed
- notes: "Standardized ZIP format" if changed

**High School (high_school):**
- Expand abbreviations: "HS" → "High School", "MS" → "Middle School"
- Keep school acronyms as-is: "MSPHS", "CHS", "LHS" are valid
- Fix obvious typos
- edit_type: "format_correction" or "none"
- notes: "Expanded abbreviation" or "" if no change

**Major:**
- CRITICAL: Preserve the exact text written on the sheet
- Fix only obvious spelling errors: "wursing" → "Nursing", "Buisness" → "Business"
- Capitalize properly
- DO NOT change to mapped value
- edit_type: "ocr_correction" or "typo_fix" if changed
- notes: "Fixed spelling error" if changed

**Mapped Major (mapped_major):**
- Match to closest major in valid_majors list
- Intelligent matching: "Business" → "Business Administration | BSBA"
- IMPORTANT: Pipe character (|) is part of the major name - don't split on it
- Common abbreviations: "Psych" → "Psychology | BS", "Comp Sci" → "Computer Science | BS"
- If no reasonable match, set value to "Undecided"
- edit_type: "mapped_value"
- notes: "Mapped to closest valid major" or "No close match found, defaulted to Undecided"

---

🧪 Quality Indicators (Same as Inquiry Cards):

**edit_made:**
- true → Value was changed from original
- false → Value unchanged

**edit_type:**
- none: No changes made
- format_correction: Formatting standardization (phone, date, state code)
- ocr_correction: Fixed OCR/handwriting reading error
- typo_fix: Fixed spelling/typo
- mapped_value: Mapped to valid options list (for mapped_major)
- unclear_text: Text is too unclear to determine value

**text_clarity:**
- clear: Handwriting is legible and clear
- mostly_clear: Handwriting is mostly legible with minor unclear parts
- unclear: Handwriting is difficult to read
- unreadable: Cannot determine text from image

**certainty:**
- certain: Confident this is the correct value
- mostly_certain: Reasonably confident, minor doubts
- uncertain: Not confident in the value

**notes:**
- Brief human-style explanation (1-2 sentences max)
- Never mention "OCR", "AI", "system", "Gemini"
- Focus on what was done or why uncertain

✅ Good Notes:
- "Fixed typo in domain"
- "Handwriting is messy - best guess"
- "Standardized to state code"
- "Mapped to closest valid major"
- "Fixed spelling error"
- ""  (empty string if no changes and clear)

🚫 Avoid:
- "OCR uncertain"
- "AI wasn't confident"
- "Low confidence from system"
- "Gemini correction"

---

⚠️ VALIDATION RULES:

1. **Row Count:** Output array must have EXACT SAME length as input array
2. **Row Numbers:** Preserve row_number field for each student (don't enhance it)
3. **Field Completeness:** Every field in input should have enhanced object in output
4. **No Row Mixing:** Data from row 1 stays in row 1, row 2 stays in row 2, etc.
5. **JSON Validity:** Output must be valid JSON array
6. **Empty Fields:** If input field is empty, output enhanced object with empty value:
   ```json
   {
     "value": "",
     "edit_made": false,
     "edit_type": "none",
     "original_value": "",
     "text_clarity": "clear",
     "certainty": "certain",
     "notes": ""
   }
   ```

---

📤 Remember:
- Input: Array of raw student records from first-pass extraction
- Output: Array of enhanced student records with quality indicators
- Same student count
- Same row numbers
- Enhanced field objects for quality tracking
- Respond ONLY with the JSON array - no markdown, no explanations

"""


def build_enhancement_prompt(raw_records: list, valid_majors: list = None) -> str:
    """
    Build the sign-up sheet enhancement prompt with raw data.

    Args:
        raw_records: List of student records from first-pass extraction
        valid_majors: List of valid major options for mapping

    Returns:
        Complete prompt string ready for Gemini
    """
    import json

    # Build input object
    input_data = {
        "students": raw_records,
        "valid_majors": valid_majors or []
    }

    # Create full prompt
    prompt = SIGNUP_ENHANCEMENT_PROMPT_TEMPLATE + f"\n\n📥 Input Data:\n{json.dumps(input_data, indent=2)}"

    return prompt
