"""
Gemini-powered transcript parsing service integrated with card-capture-api.
"""
import json
import os
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional
import google.generativeai as genai

from app.config import GEMINI_API_KEY
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug
from .format_detector import TranscriptFormatDetector
from .validation_engine import TranscriptValidator


TRANSCRIPT_EXTRACTION_PROMPT = """
You are an expert transcript parser for US high school academic records.

TASK: Extract all student and course information from this transcript image/PDF into structured JSON, then recalculate GPA using weighted 4.0 scale.

IMPORTANT: If courses are split by semester (Part 1/Part 2, Semester 1/Semester 2), COMBINE them into single course entries:
- Average the semester grades to get final_grade_numeric
- Sum the credits from both parts
- Store individual semester grades in semester_grades object

GPA CALCULATION RULES (CRITICAL):
- Use weighted 4.0 scale: A (90-100+, including A-, A, A+) = 4 points, B (80-89, including B-, B, B+) = 3 points, C (70-79, including C-, C, C+) = 2 points, D (60-69, including D-, D, D+) = 1 point, F (0-59) = 0 points
- WEIGHT BONUS CALCULATION: For advanced courses with grade 60+ (D or better), ADD +1.0 to base points
  Example: Dual Credit English with B grade = 3.0 base + 1.0 bonus = 4.0 total points
- Advanced courses marked as: H, Q, D, P, I, K or labeled Honors, Pre-AP, AP, IB, Pre-IB, Dual Credit
- Include grades 9th-12th PLUS any courses marked with J (J means counts toward high school credit even if taken before 9th grade)
- Include ALL courses with grades, even if student received no credit for the class
- Use final/average grade for calculation (not individual semester grades)

COMMON COURSE FLAGS & MEANINGS:
- P, AP = Advanced Placement (+1.0 weight if D or better)
- I, IB = International Baccalaureate (+1.0 weight if D or better)
- D, DC = Dual Credit (+1.0 weight if D or better)
- H = Honors (+1.0 weight if D or better)
- Q = Pre-AP/Pre-Advanced Placement (+1.0 weight if D or better)
- K = Pre-IB (+1.0 weight if D or better)
- J = Counts toward high school credit (INCLUDE in GPA even if taken before 9th grade)
- R = Repeated course (include in GPA)
- Z = Distance learning (include in GPA)
- * = Credit denied (include grade in GPA even if no credit awarded)
- L = Local credit only (include in GPA)

TRANSCRIPT FORMATS TO RECOGNIZE:
1. Texas AAR: "22/23 ENG 1  85  87  86  1.00  P" (year/course/S1/S2/avg/credits/flags)
2. Semester blocks: Course lists under semester headers
3. Grid format: Courses in tables with semester columns
4. Course codes: (S)1234567, subject abbreviations like ENG, ALG, BIO

EXTRACT INTO THIS JSON:
{
  "student": {
    "name": "Last, First Middle",
    "date_of_birth": "YYYY-MM-DD",
    "student_id": "ID number",
    "school": "School Name",
    "district": "District Name",
    "reported_gpa": 3.45,
    "class_rank": 25,
    "class_size": 400
  },
  "courses": [
    {
      "school_year": "2022-23",
      "term": "Fall",
      "grade_level": "11",
      "course_code": "ENG301",
      "course_name": "English 3",
      "credits_attempted": 1.0,
      "credits_earned": 0.0,
      "final_grade_numeric": 86,
      "final_grade_letter": "B",
      "semester_grades": {"s1": 85, "s2": 87},
      "advanced_course": true,
      "weight_eligible": true,
      "include_in_gpa": true,
      "raw_text": "22/23 ENG 3  85  87  86  1.00  H",
      "confidence": 0.95
    }
  ],
  "gpa_calculation": {
    "total_quality_points": 45.5,
    "total_credits": 12.0,
    "calculated_gpa": 3.79,
    "courses_included": 12,
    "weighted_courses": 8
  },
  "parsing_notes": ["Found legend defining course flags", "All grades clearly visible"]
}

CRITICAL INSTRUCTIONS:
1. ALWAYS include courses with grades even if credits_earned = 0
2. Weight bonus of +1.0 ONLY applies if final grade is 60+ (D or better)
3. INCLUDE courses marked with J in GPA calculation (J means counts toward HS credit)
4. Look for legends/keys that define flag meanings
5. Use final/average grade, not semester grades, for GPA calculation
6. Mark advanced courses correctly - look for H,Q,D,P,I,K flags or Honors/AP/IB/Pre-AP/Dual Credit in course names
7. ALL advanced course types (Honors, Pre-AP, AP, IB, Pre-IB, Dual Credit) get +1.0 weight bonus if grade is D or better
8. Calculate total quality points: (base_grade_points + weight_bonus) × credits
9. WEIGHT BONUS EXAMPLE: Dual Credit History with A grade = 4.0 base + 1.0 bonus = 5.0 total points, then 5.0 × 1.0 credit = 5.0 quality points
10. If unsure about a grade or flag, note it in parsing_notes and set confidence < 0.8
11. KEEP parsing_notes brief and avoid quotes inside note text to prevent JSON errors

Return ONLY valid JSON. Ensure all quotes in text fields are properly escaped.
"""


class GeminiTranscriptService:
    """Gemini-powered transcript parsing service."""
    
    def __init__(self):
        """Initialize with existing card-capture Gemini configuration."""
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not found in environment")
        
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
        self.detector = TranscriptFormatDetector()
        self.validator = TranscriptValidator()
    
    def parse_transcript(self, file_path: str) -> Dict[str, Any]:
        """
        Parse transcript using Gemini Vision API.
        
        Args:
            file_path: Path to transcript file (PDF, PNG, JPG, etc.)
            
        Returns:
            Dictionary with extracted transcript data
        """
        log_debug("=== TRANSCRIPT PARSING START ===", service="transcript_parser")
        log_debug(f"File path: {file_path}", service="transcript_parser")
        
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            # Determine MIME type
            mime_type = self._get_mime_type(file_path)
            log_debug(f"Detected MIME type: {mime_type}", service="transcript_parser")
            
            # Read file data
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            log_debug(f"File size: {len(file_data)} bytes", service="transcript_parser")
            
            # Stage 1: quick format detection to improve consistency
            # (send a tiny preface for Gemini to output raw text summary, then do simple heuristics locally)
            detection_prompt = "Summarize layout cues only: headers, presence of S1/S2/AVG/CR, grid headers, semester blocks. Return a short plain text list."
            detection_resp = retry_with_exponential_backoff(
                func=lambda: self.model.generate_content([detection_prompt, {"mime_type": mime_type, "data": file_data}]),
                max_retries=1,
                operation_name="Gemini format sniff",
                service="transcript_parser"
            )
            detection_text = detection_resp.text or ""
            format_info = self.detector.analyze_text(detection_text)
            log_debug(f"Format detection: {format_info}", service="transcript_parser")

            # Create prompt parts for extraction (Stage 2)
            prompt_parts = [TRANSCRIPT_EXTRACTION_PROMPT]
            # Nudge Gemini lightly using format hints
            format_nudge = f"\nFormat hints: format_type={format_info['format_type']}, grade_scale={format_info['grade_scale']}, credit_system={format_info['credit_system']}\n"
            prompt_parts[0] = prompt_parts[0] + format_nudge
            prompt_parts.append({"mime_type": mime_type, "data": file_data})
            
            # Generate response with retry logic (following card-capture pattern)
            log_debug("Sending request to Gemini for transcript parsing...", service="transcript_parser")
            
            response = retry_with_exponential_backoff(
                func=lambda: self.model.generate_content(prompt_parts),
                max_retries=3,
                operation_name="Gemini transcript parsing",
                service="transcript_parser"
            )
            
            if not response or not response.text:
                raise Exception("Empty response from Gemini")
            
            log_debug("Raw Gemini response received", service="transcript_parser")
            log_debug(f"Response length: {len(response.text)}", service="transcript_parser")
            
            # Parse JSON response
            transcript_data = self._parse_response(response.text)

            # Normalize field names and combine semester splits
            try:
                transcript_data = self._normalize_and_combine_courses(transcript_data)
            except Exception as e:
                log_debug(f"Error during normalization/combination: {e}", service="transcript_parser")

            transcript_data = self._apply_default_policy_and_recalc(transcript_data)

            # Validate and auto-retry once with targeted corrections
            issues = self.validator.validate(transcript_data)
            if issues:
                log_debug(f"Validation issues detected: {issues}", service="transcript_parser")
                correction_prompt = self._build_correction_prompt(issues, prior_json=transcript_data)
                retry_resp = retry_with_exponential_backoff(
                    func=lambda: self.model.generate_content([correction_prompt, {"mime_type": mime_type, "data": file_data}]),
                    max_retries=1,
                    operation_name="Gemini correction retry",
                    service="transcript_parser"
                )
                if retry_resp and retry_resp.text:
                    try:
                        corrected = self._parse_response(retry_resp.text)
                        corrected = self._normalize_and_combine_courses(corrected)
                        corrected = self._apply_default_policy_and_recalc(corrected)
                    except Exception as e:
                        log_debug(f"Retry parse failed, using original output: {e}", service="transcript_parser")
                        corrected = transcript_data
                    # Keep corrected if it resolves issues better
                    new_issues = self.validator.validate(corrected)
                    if len(new_issues) <= len(issues):
                        log_debug("Applied corrected extraction after retry", service="transcript_parser")
                        transcript_data = corrected
            
            log_debug("Transcript parsing completed successfully", service="transcript_parser")
            log_debug(f"Extracted {len(transcript_data.get('courses', []))} courses", service="transcript_parser")
            
            return transcript_data
            
        except Exception as e:
            log_debug(f"Error in transcript parsing: {str(e)}", service="transcript_parser")
            raise

    def _build_correction_prompt(self, issues: list, prior_json: Optional[dict] = None) -> str:
        fixes = []
        if any("Pass/CR" in s for s in issues):
            fixes.append("Exclude courses with final grade letter P/CR from GPA and recalculate.")
        if any("Junior-high" in s for s in issues):
            fixes.append("INCLUDE courses marked with J (they count toward HS credit).")
        if any("Calculated GPA" in s for s in issues):
            fixes.append("Ensure calculated_gpa is within 0.0–5.0 range.")
        if any("Total credits" in s for s in issues):
            fixes.append("Ensure total_credits equals the sum of credits_attempted for include_in_gpa=true courses.")
        if any("Weights must only apply" in s for s in issues):
            fixes.append("Apply +1.0 weight bonuses only when final grade >= 60 (D or better).")

        if not fixes:
            fixes.append("Recheck inclusion rules and recompute GPA/credits accurately.")

        prior_block = ""
        if prior_json:
            try:
                prior_block = "\nHere is your previous JSON output. Use it as a base, and only correct the issues listed. Do NOT remove required keys.\nPREVIOUS_JSON:\n" + json.dumps(prior_json, ensure_ascii=False)
            except Exception:
                prior_block = ""

        return (
            "You previously extracted transcript data but some validation issues were found.\n"
            "Apply ONLY these corrections and return FULL JSON matching the SAME schema (include 'student', 'courses', 'gpa_calculation', 'parsing_notes').\n"
            "Do NOT omit sections. Keep all unchanged values intact; only modify fields required to resolve issues.\n"
            "Ensure output is valid JSON (no trailing commas; escape quotes in text fields).\n"
            "Corrections to apply:\n- " + "\n- ".join(fixes) + prior_block
        )

    def _normalize_and_combine_courses(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize field names and combine semester-split courses.

        Some transcripts list each course twice (Part 1 and Part 2 for each semester).
        This function:
        1. Normalizes field names (grade_value -> final_grade_numeric, etc.)
        2. Combines semester splits by averaging grades and summing credits
        """
        courses = data.get("courses", [])

        # Step 1: Normalize field names
        for course in courses:
            # Map alternate field names to standard schema
            if "grade_value" in course and "final_grade_numeric" not in course:
                course["final_grade_numeric"] = course.get("grade_value")

            if "credit_earned" in course and "credits_earned" not in course:
                course["credits_earned"] = course.get("credit_earned")

            if "credit_earned" in course and "credits_attempted" not in course:
                course["credits_attempted"] = course.get("credit_earned")

            if "course_description" in course and "course_name" not in course:
                course["course_name"] = course.get("course_description")

            if "course" in course and "course_code" not in course:
                course["course_code"] = course.get("course")

        # Step 2: Detect and combine semester-split courses
        # Check if this is a semester-split format (has "part" field)
        has_parts = any("part" in c for c in courses)

        if has_parts:
            log_debug("Detected semester-split format, combining courses...", service="transcript_parser")

            # Group courses by service_id or course_code + course_name
            # NOTE: Don't include year because parts span calendar years (Dec 2024 + May 2025)
            course_groups = {}
            for course in courses:
                # Create a key to identify matching courses
                service_id = course.get("service_id", "")
                course_code = course.get("course_code", "")
                course_name = course.get("course_name", "")

                # Use service_id as primary key, fallback to course_code + name
                if service_id:
                    key = f"svc_{service_id}"
                else:
                    key = f"code_{course_code}_{course_name}"

                if key not in course_groups:
                    course_groups[key] = []
                course_groups[key].append(course)

            # Combine grouped courses
            combined_courses = []
            for key, group in course_groups.items():
                if len(group) == 1:
                    # Single course, just use as is
                    combined_courses.append(group[0])
                else:
                    # Multiple parts, combine them
                    combined = self._combine_course_parts(group)
                    combined_courses.append(combined)

            log_debug(f"Combined {len(courses)} semester entries into {len(combined_courses)} courses",
                     service="transcript_parser")
            data["courses"] = combined_courses

        return data

    def _combine_course_parts(self, parts: list) -> Dict[str, Any]:
        """Combine multiple course parts (semesters) into one course entry."""
        if not parts:
            return {}

        # Use first part as base
        combined = parts[0].copy()

        # Average numeric grades
        grades = [p.get("final_grade_numeric") or p.get("grade_value") for p in parts if p.get("final_grade_numeric") or p.get("grade_value")]
        if grades:
            combined["final_grade_numeric"] = round(sum(grades) / len(grades), 1)

        # Sum credits
        credits_earned = sum([float(p.get("credits_earned") or p.get("credit_earned") or 0) for p in parts])
        credits_attempted = sum([float(p.get("credits_attempted") or p.get("credit_earned") or 0) for p in parts])
        combined["credits_earned"] = credits_earned
        combined["credits_attempted"] = credits_attempted

        # Store semester grades
        semester_grades = {}
        for i, part in enumerate(parts, 1):
            grade = part.get("final_grade_numeric") or part.get("grade_value")
            if grade:
                semester_grades[f"s{i}"] = grade
        combined["semester_grades"] = semester_grades

        # Combine raw text
        raw_texts = [p.get("raw_text", "") for p in parts if p.get("raw_text")]
        combined["raw_text"] = " | ".join(raw_texts) if raw_texts else None

        # Remove the "part" field since it's now combined
        combined.pop("part", None)

        return combined

    def _apply_default_policy_and_recalc(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply default inclusion rules and recalc GPA for PoC consistency."""
        courses = data.get("courses", [])

        def is_pe_or_ath(name: str) -> bool:
            if not name or name is None:
                return False
            n = str(name).upper()
            pe_tokens = [" PE ", " P.E", " ATH ", "ATHL", "ATHLET", "SUBATH", "PES", "PHYSICAL EDUCATION"]
            return any(tok.strip() in n for tok in pe_tokens) or n.startswith("PE") or n.startswith("P.E")

        def is_elective(name: Optional[str], code: Optional[str]) -> bool:
            n = str(name or "").upper()
            c = str(code or "").upper()
            # CTE courses often start with 13xxxxx (Texas TEKS)
            if c.startswith("13"):
                return True
            elective_tokens = [
                "ART", "MUSIC", "CHOIR", "BAND", "ORCHESTRA", "THEATER", "DRAMA", "DANCE",
                "JOURNALISM", "YEARBOOK", "PHOTO", "PHOTOGRAPHY",
                "ACCOUNT", "BUS", "BUSINESS", "MARKETING",
                "CULINARY", "CULART", "HOSPITALITY",
                "ANIMAT", "GAME", "GRAPHIC", "MEDIA",
                "PRACTICUM", "INTERNSHIP", "INPRAC",
                "HUMAN GROWTH", "HUGRDEV",
                "MONEY", "FINANCE", "MONEYM",
                "LDWRTY",  # Language Development/Writing elective in samples
            ]
            return any(tok in n for tok in elective_tokens)

        def letter_points(grade_letter: Optional[str], grade_numeric: Optional[float]) -> float:
            if grade_letter and grade_letter is not None:
                g = str(grade_letter).upper()
                if g == "A" or (grade_numeric is not None and grade_numeric >= 90):
                    return 4.0
                if g == "B" or (grade_numeric is not None and 80 <= grade_numeric < 90):
                    return 3.0
                if g == "C" or (grade_numeric is not None and 70 <= grade_numeric < 80):
                    return 2.0
                if g == "D" or (grade_numeric is not None and 60 <= grade_numeric < 70):
                    return 1.0
                return 0.0
            # no letter, use numeric
            if grade_numeric is None:
                return 0.0
            if grade_numeric >= 90:
                return 4.0
            if grade_numeric >= 80:
                return 3.0
            if grade_numeric >= 70:
                return 2.0
            if grade_numeric >= 60:
                return 1.0
            return 0.0

        def weight_bonus_for(course: Dict[str, Any]) -> float:
            # Check if grade is D or better (60+)
            grade_num = course.get("final_grade_numeric")
            grade_letter_raw = course.get("final_grade_letter")
            grade_letter = str(grade_letter_raw or "").upper() if grade_letter_raw else ""

            # Determine if grade is 60+ (D or better)
            passing_grade = False
            if grade_num is not None and grade_num >= 60:
                passing_grade = True
            elif grade_letter and grade_letter in ["A", "B", "C", "D"]:
                passing_grade = True

            if not passing_grade:
                return 0.0

            # ALL advanced courses get +1.0 weight bonus (customer requirement)
            # Check for: H, Q, D, P, I, K flags or Honors, Pre-AP, AP, IB, Pre-IB, Dual Credit
            # Use raw_text to check for flag markers (more reliable than course name)
            raw_text = course.get("raw_text")
            raw = str(raw_text or "").upper() if raw_text else ""

            # Check for colon-prefixed flags (most reliable)
            if any(flag in raw for flag in [":H", ":Q", ":D", ":P", ":I", ":K"]):
                # Exclude :J which is just for HS credit, not weight
                if ":J" in raw and not any(f in raw for f in [":H", ":Q", ":D", ":P", ":I", ":K"]):
                    return 0.0
                return 1.0

            # Check for keyword markers
            course_name = course.get("course_name")
            name_str = str(course_name or "") if course_name else ""
            name_and_raw = name_str + " " + raw
            name_u = name_and_raw.upper()
            advanced_keywords = [
                "HONORS", "PRE-AP", "PREAP", "PRE AP",
                "DUAL CREDIT", "DUAL-CREDIT",
                " AP ", "^AP ", " AP$",  # AP (avoid matching in middle of words)
                " IB ", "^IB ", " IB$",   # IB
                "PRE-IB", "PREIB", "PRE IB"
            ]
            if any(k in name_u for k in advanced_keywords):
                return 1.0

            # fallback to advanced_course flag
            if course.get("advanced_course") is True:
                return 1.0
            return 0.0

        total_qp = 0.0
        total_cr = 0.0

        for c in courses:
            # Customer requirement: Include ALL courses with grades from 9-12
            # PLUS courses marked with J (count toward HS credit even if taken before 9th grade)
            include = True
            reasons = []

            # ONLY exclude pass/fail courses (no numeric grade to calculate)
            fl_raw = c.get("final_grade_letter")
            fl = str(fl_raw or "").upper() if fl_raw else ""
            if fl in ["P", "CR"]:
                include = False
                reasons.append("pass_fail")

            # Exclude courses with no grade information at all
            grade_num = c.get("final_grade_numeric")
            if grade_num is None and not c.get("final_grade_letter"):
                include = False
                reasons.append("no_grade")

            c["include_in_gpa"] = include
            if not include:
                c["exclusion_reason"] = ",".join(reasons) if reasons else "policy"

            if include:
                ca = float(c.get("credits_attempted") or 0)
                # Use credits_attempted for GPA calculation (customer includes all courses with grades)
                if ca <= 0:
                    ca = 1.0  # Default to 1.0 credit if not specified but has a grade

                base = letter_points(c.get("final_grade_letter"), c.get("final_grade_numeric"))
                bonus = weight_bonus_for(c)
                qp = (base + bonus) * ca
                total_qp += qp
                total_cr += ca

            # Store debug calc regardless for reconciliation output
            ca_debug = float(c.get("credits_attempted") or 1.0)
            c["base_points"] = letter_points(c.get("final_grade_letter"), c.get("final_grade_numeric"))
            c["weight_points"] = weight_bonus_for(c)
            c["quality_points"] = (c["base_points"] + c["weight_points"]) * ca_debug

        calc_gpa = round(total_qp / total_cr, 3) if total_cr > 0 else 0.0
        data["gpa_calculation"] = {
            "total_quality_points": round(total_qp, 2),
            "total_credits": round(total_cr, 2),
            "calculated_gpa": calc_gpa,
            "courses_included": len([c for c in courses if c.get("include_in_gpa")]),
            "weighted_courses": len([c for c in courses if c.get("include_in_gpa") and weight_bonus_for(c) > 0]),
        }
        return data
    
    def _get_mime_type(self, file_path: Path) -> str:
        """Get MIME type for file."""
        mime_type, _ = mimetypes.guess_type(str(file_path))
        
        if mime_type is None:
            # Default based on extension
            ext = file_path.suffix.lower()
            mime_map = {
                '.pdf': 'application/pdf',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.tiff': 'image/tiff',
                '.bmp': 'image/bmp'
            }
            mime_type = mime_map.get(ext, 'application/octet-stream')
        
        return mime_type
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse and validate Gemini response."""
        try:
            # Clean the response text (remove markdown formatting)
            cleaned_text = response_text.strip()
            if cleaned_text.startswith('```json'):
                cleaned_text = cleaned_text[7:]
            elif cleaned_text.startswith('```'):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith('```'):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            # Additional JSON cleaning for common issues
            cleaned_text = self._clean_json_response(cleaned_text)
            
            # Parse JSON
            transcript_data = json.loads(cleaned_text)
            
            # Basic validation
            self._validate_response(transcript_data)
            
            return transcript_data
            
        except json.JSONDecodeError as e:
            log_debug(f"JSON parsing error: {str(e)}", service="transcript_parser")
            log_debug(f"Error location: line {e.lineno}, column {e.colno}", service="transcript_parser")
            
            # Try to extract partial valid JSON
            try:
                partial_data = self._extract_partial_json(cleaned_text)
                log_debug("Successfully recovered partial JSON data", service="transcript_parser")
                return partial_data
            except:
                log_debug(f"Failed to recover partial JSON", service="transcript_parser")
                log_debug(f"Response text preview: {response_text[:1000]}...", service="transcript_parser")
                raise ValueError(f"Invalid JSON response from Gemini: {str(e)}")
        except Exception as e:
            log_debug(f"Error parsing response: {str(e)}", service="transcript_parser")
            raise
    
    def _clean_json_response(self, text: str) -> str:
        """Clean common JSON formatting issues in Gemini responses."""
        # Fix common issues with quotes in parsing notes
        lines = text.split('\n')
        cleaned_lines = []
        in_parsing_notes = False
        
        for line in lines:
            # Track if we're in parsing_notes array
            if '"parsing_notes"' in line:
                in_parsing_notes = True
            elif in_parsing_notes and line.strip().startswith(']'):
                in_parsing_notes = False
            
            # Fix unescaped quotes in parsing notes
            if in_parsing_notes and line.strip().startswith('"'):
                # Escape internal quotes but not the wrapping quotes
                if line.count('"') > 2:  # More than just start/end quotes
                    # Find the content between first and last quote
                    first_quote = line.find('"')
                    last_quote = line.rfind('"')
                    if first_quote != last_quote:
                        content = line[first_quote+1:last_quote]
                        # Escape internal quotes
                        escaped_content = content.replace('"', '\\"')
                        line = line[:first_quote+1] + escaped_content + line[last_quote:]
            
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _extract_partial_json(self, text: str) -> Dict[str, Any]:
        """Try to extract valid JSON from a partially corrupted response."""
        # Find the main JSON structure
        start_idx = text.find('{')
        if start_idx == -1:
            raise ValueError("No JSON object found")
        
        # Try to find a valid ending point by looking for key sections
        essential_sections = ['"student"', '"courses"', '"gpa_calculation"']
        
        # Find the last essential section
        last_section_end = 0
        for section in essential_sections:
            section_idx = text.rfind(section)
            if section_idx > last_section_end:
                # Find the end of this section
                brace_count = 0
                in_string = False
                escape_next = False
                
                for i in range(section_idx, len(text)):
                    char = text[i]
                    
                    if escape_next:
                        escape_next = False
                        continue
                    
                    if char == '\\':
                        escape_next = True
                        continue
                    
                    if char == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    
                    if not in_string:
                        if char == '{' or char == '[':
                            brace_count += 1
                        elif char == '}' or char == ']':
                            brace_count -= 1
                            if brace_count == 0:
                                last_section_end = i + 1
                                break
        
        if last_section_end > start_idx:
            # Try to create a valid JSON by truncating at a safe point
            partial_text = text[start_idx:last_section_end]
            # Ensure it ends properly
            if not partial_text.endswith('}'):
                partial_text += '}'
            
            try:
                return json.loads(partial_text)
            except:
                pass
        
        # Fallback: create minimal valid structure
        return {
            "student": {"name": "Parse Error", "reported_gpa": None},
            "courses": [],
            "gpa_calculation": {"calculated_gpa": 0, "total_credits": 0},
            "parsing_notes": ["JSON parsing error - partial data may be missing"]
        }
    
    def _validate_response(self, data: Dict[str, Any]):
        """Basic validation of Gemini response structure."""
        required_keys = ['student', 'courses']
        
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Missing required key: {key}")
        
        if not isinstance(data['courses'], list):
            raise ValueError("Courses must be a list")
        
        log_debug(f"Validation passed - found {len(data['courses'])} courses", service="transcript_parser")


def parse_transcript_file(file_path: str) -> Dict[str, Any]:
    """
    Convenience function to parse a transcript file.
    
    Args:
        file_path: Path to transcript file
        
    Returns:
        Parsed transcript data
    """
    service = GeminiTranscriptService()
    return service.parse_transcript(file_path)
