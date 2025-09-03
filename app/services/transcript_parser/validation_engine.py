"""
Lightweight validation for PoC: checks common consistency problems and
returns a list of human-readable issue strings to feed back to Gemini.
"""
from typing import Dict, List


class TranscriptValidator:
    def validate(self, data: Dict) -> List[str]:
        issues: List[str] = []

        student = data.get("student", {})
        courses = data.get("courses", [])
        gpa = data.get("gpa_calculation", {})

        # Basic structure
        if not isinstance(courses, list) or len(courses) == 0:
            issues.append("No courses parsed; ensure course rows are extracted.")

        # GPA range sanity
        calc_gpa = gpa.get("calculated_gpa")
        if calc_gpa is not None and (calc_gpa < 0 or calc_gpa > 5):
            issues.append("Calculated GPA must be in 0.0–5.0 range; recompute correctly.")

        # Credits consistency
        total_credits = gpa.get("total_credits") or 0
        sum_credits = 0.0
        for c in courses:
            if c.get("include_in_gpa", True):
                sum_credits += float(c.get("credits_attempted") or 0)
        if total_credits and abs(sum_credits - total_credits) > 1.0:
            issues.append("Total credits do not match sum of course credits; fix credits and totals.")

        # Exclusions: pass/fail (P/Pass/CR) should not count in GPA
        pf_included = [c for c in courses if (c.get("final_grade_letter", "").upper() in ["P", "CR"]) and c.get("include_in_gpa", True)]
        if pf_included:
            issues.append("Pass/CR courses must be excluded from GPA.")

        # Junior-high exclusion
        j_included = [c for c in courses if c.get("grade_level") == "J" and c.get("include_in_gpa", True)]
        if j_included:
            issues.append("Junior-high (J) courses must be excluded from GPA.")

        # Weight eligibility
        weight_errors = []
        for c in courses:
            adv = c.get("advanced_course", False)
            grade = c.get("final_grade_numeric")
            if adv and grade is not None and grade < 60 and c.get("weight_eligible", False):
                weight_errors.append(c)
        if weight_errors:
            issues.append("Weights must only apply when final grade >= 60 (D or better).")

        return issues


