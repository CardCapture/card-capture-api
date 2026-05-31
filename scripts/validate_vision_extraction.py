"""
Local validation harness for the vision-only extraction path (DocAI removal).

Runs process_card_with_gemini_vision against real sample cards using each
school's real card_fields + majors pulled from the connected DB. Read-only:
reports the orientation Gemini detects but does NOT re-save images to storage.

Usage:
    source venv/bin/activate && python scripts/validate_vision_extraction.py
"""
import sys
import time

from app.core.clients import get_supabase_client
from app.utils.image_processing import ensure_proper_orientation
from app.services.gemini_vision_service import process_card_with_gemini_vision


# (label, image_path, school_name)
# Schools are resolved by name, not ID, so this runs against any environment
# (staging or prod) without editing hardcoded IDs.
TARGETS = [
    ("UNIVERSAL CARD", "universal_card.jpg", "CardCapture Test School"),
    ("MISSISSIPPI COLLEGE", "MC/IMG_6958.jpg", "Mississippi College"),
    ("ABILENE CHRISTIAN (ACU)", "ACU/acu1.jpg", "Abilene Christian University"),
]


def load_school(sb, school_name):
    res = (
        sb.table("schools")
        .select("name,card_fields,majors")
        .eq("name", school_name)
        .order("id")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else {}


def main():
    sb = get_supabase_client()
    for label, image_path, school_name in TARGETS:
        school = load_school(sb, school_name)
        card_fields = school.get("card_fields") or []
        majors = school.get("majors") or []

        print("\n" + "=" * 78)
        print(f"{label}  |  {school.get('name')}  |  {image_path}")
        print(f"configured fields: {len(card_fields)}   majors: {len(majors)}")
        print("=" * 78)

        working = ensure_proper_orientation(image_path)
        t0 = time.monotonic()
        try:
            result = process_card_with_gemini_vision(working, card_fields, majors)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        elapsed = time.monotonic() - t0

        fields = result["fields"]
        print(f"  latency: {elapsed:.1f}s   image_rotation_degrees: {result['image_rotation_degrees']}")
        discovered = result.get("discovered_keys") or []
        configured_keys = {f.get("key") for f in card_fields if isinstance(f, dict)}
        print("  --- configured fields ---")
        for key in [f.get("key") for f in card_fields if isinstance(f, dict)]:
            fd = fields.get(key)
            if not fd:
                continue
            val = fd.get("value", "")
            cert = fd.get("certainty", "?")
            clarity = fd.get("text_clarity", "?")
            orig = fd.get("original_value", "")
            flag = ""
            if orig and orig != val:
                flag = f"   (read: {orig!r})"
            print(f"    {key:22} = {val!r:38} [{clarity}/{cert}]{flag}")
        if discovered:
            print("  --- discovered (would become suggestions) ---")
            for key in discovered:
                fd = fields.get(key, {})
                print(f"    {key:22} = {fd.get('value','')!r:38} [type={fd.get('field_type','text')}]")
        else:
            print("  --- discovered: none ---")


if __name__ == "__main__":
    sys.exit(main())
