"""
Lightweight transcript format detector for PoC.
Returns a small dict used to guide extraction prompts and validation.
"""
from typing import Dict


class TranscriptFormatDetector:
    def analyze_text(self, text: str) -> Dict:
        text_lower = text.lower()

        # Heuristics for common layouts
        if "s1s2avg cr" in text_lower or "passing is" in text_lower or "(s)0" in text_lower:
            fmt = "texas_aar"
        elif "course title" in text_lower and "sem 1" in text_lower and "sem 2" in text_lower:
            fmt = "private_school_grid"
        elif "ib" in text_lower or "hl" in text_lower or "sl" in text_lower:
            fmt = "ib_program"
        elif "fall" in text_lower and "spring" in text_lower and "student aca lvl" in text_lower:
            fmt = "semester_blocks"
        else:
            fmt = "unknown"

        # Grade scale heuristic
        if any(k in text_lower for k in ["a+", "b-", "c+", "d-", " gpa "]):
            grade_scale = "4.0"
        elif "%" in text_lower:
            grade_scale = "percentage"
        elif any(k in text_lower for k in [" 100 ", " 99 ", " 98 "]):
            grade_scale = "100_point"
        else:
            grade_scale = "unknown"

        # Credit system heuristic
        if "0.50" in text or " .50" in text:
            credit_system = "semester"
        else:
            credit_system = "unknown"

        return {
            "format_type": fmt,
            "grade_scale": grade_scale,
            "credit_system": credit_system,
            "confidence": 0.8 if fmt != "unknown" else 0.5,
        }


