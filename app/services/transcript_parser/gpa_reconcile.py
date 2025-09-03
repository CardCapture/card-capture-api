"""
Reconciliation helper: compute GPA under multiple policy variants and
compare against reported GPA to identify which rules explain the gap.
"""
from typing import Dict, List, Tuple


def compute_gpa_variants(data: Dict) -> List[Tuple[str, float, float]]:
    courses = data.get("courses", [])
    reported = (data.get("student", {}) or {}).get("reported_gpa") or 0.0

    def base_points(grade_letter, grade_num):
        if grade_letter:
            g = grade_letter.upper()
            if g == "A" or (grade_num is not None and grade_num >= 90):
                return 4.0
            if g == "B" or (grade_num is not None and 80 <= grade_num < 90):
                return 3.0
            if g == "C" or (grade_num is not None and 70 <= grade_num < 80):
                return 2.0
            if g == "D" or (grade_num is not None and 60 <= grade_num < 70):
                return 1.0
            return 0.0
        if grade_num is None:
            return 0.0
        return 4.0 if grade_num >= 90 else 3.0 if grade_num >= 80 else 2.0 if grade_num >= 70 else 1.0 if grade_num >= 60 else 0.0

    # Variant A: current default (earned-credit denominator, excludes J/PE/electives/pass-fail/zero-credit)
    def variant_default() -> float:
        total_qp = 0.0
        total_cr = 0.0
        for c in courses:
            if not c.get("include_in_gpa", False):
                continue
            ca = float(c.get("credits_attempted") or 0)
            bp = base_points(c.get("final_grade_letter"), c.get("final_grade_numeric"))
            total_qp += bp * ca
            total_cr += ca
        return round(total_qp / total_cr, 3) if total_cr > 0 else 0.0

    # Variant B: attempted-credit denominator (include rows with credits_attempted > 0 even if credit_earned == 0)
    # Still exclude J, PE, Pass/CR. Electives toggled separately.
    def variant_attempted(include_electives: bool) -> float:
        total_qp = 0.0
        total_cr = 0.0
        for c in courses:
            name_u = (c.get("course_name") or "").upper()
            fl = (c.get("final_grade_letter") or "").upper()
            ca = float(c.get("credits_attempted") or 0)
            if ca <= 0:
                continue
            # Exclusions
            if c.get("grade_level") == "J":
                continue
            if fl in ["P", "CR"]:
                continue
            if any(tok in name_u for tok in [" PE ", "P.E", "ATH", "SUBATH", "PHYSICAL EDUCATION", "PES"]):
                continue
            if not include_electives and _is_elective(name_u, (c.get("course_code") or "").upper()):
                continue
            bp = base_points(c.get("final_grade_letter"), c.get("final_grade_numeric"))
            total_qp += bp * ca
            total_cr += ca
        return round(total_qp / total_cr, 3) if total_cr > 0 else 0.0

    g_default = variant_default()
    g_attempted_no_elect = variant_attempted(include_electives=False)
    g_attempted_with_elect = variant_attempted(include_electives=True)

    return [
        ("reported_gpa", float(reported), 0.0),
        ("default_policy_gpa", g_default, g_default - reported),
        ("attempted_denom_excl_electives", g_attempted_no_elect, g_attempted_no_elect - reported),
        ("attempted_denom_incl_electives", g_attempted_with_elect, g_attempted_with_elect - reported),
    ]


def _is_elective(name_u: str, code_u: str) -> bool:
    if code_u.startswith("13"):
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
        "LDWRTY",
    ]
    return any(tok in name_u for tok in elective_tokens)


