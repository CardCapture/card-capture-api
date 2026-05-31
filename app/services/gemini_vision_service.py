"""
Vision-only card extraction using Gemini 2.5 Flash and the streamlined prompt.

This is the replacement for the DocAI + Gemini pipeline. It sends the raw card
image and the streamlined prompt to Gemini in a single call and returns the
same field-dict shape that ``process_card_with_gemini_v2`` produces, so the
existing ``parse_gemini_quality_response`` and the downstream FieldData
conversion in ``pipeline._extract`` keep working unchanged.

Two extras ride the same call:
- ``image_rotation_degrees``: clockwise degrees needed to make the card upright,
  used to re-save a correctly-oriented image (replaces DocAI rotation).
- ``discovered_keys``: clearly-labeled fields Gemini saw that are not in the
  school's configured card_fields. Captured as onboarding suggestions.
"""
import io
import json
import mimetypes
import os
from typing import Any, Dict, List

from app.core.clients import get_gemini_client, get_supabase_client
from app.core.streamlined_prompt import render_streamlined_prompt
from app.services.gemini_service import parse_gemini_quality_response
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug

_VALID_ROTATIONS = {0, 90, 180, 270}


def _mime_for(path: str) -> str:
    m, _ = mimetypes.guess_type(path)
    if m and m.startswith("image/"):
        return m
    ext = os.path.splitext(path)[1].lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def _pop_rotation(parsed: dict) -> int:
    """Pop the _meta block and return a validated clockwise rotation (0/90/180/270)."""
    if not isinstance(parsed, dict):
        return 0
    meta = parsed.pop("_meta", None)
    if not isinstance(meta, dict):
        return 0
    try:
        degrees = int(meta.get("image_rotation_degrees", 0) or 0) % 360
    except (TypeError, ValueError):
        return 0
    if degrees not in _VALID_ROTATIONS:
        log_debug(f"Ignoring out-of-range rotation value: {degrees}", service="gemini_vision")
        return 0
    return degrees


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


def _build_placeholder_fields(card_fields: List[dict]) -> Dict[str, Any]:
    """
    Build an empty field dict from the school's card_fields config.

    parse_gemini_quality_response uses this as the base for each field so that
    enabled/required flags (and therefore the required-field review logic) match
    the configured settings. Mirrors the role docai_fields played in the old
    path.
    """
    placeholder: Dict[str, Any] = {}
    for f in card_fields or []:
        if not isinstance(f, dict):
            continue
        key = f.get("key") or f.get("name") or f.get("field_name")
        if not key:
            continue
        placeholder[key] = {
            "value": "",
            "confidence": 0.0,
            "source": "gemini_vision",
            "enabled": f.get("enabled", True),
            "required": f.get("required", False),
        }
    return placeholder


def process_card_with_gemini_vision(
    image_path: str,
    card_fields: List[dict],
    valid_majors: List[str],
    model: str = None,
) -> Dict[str, Any]:
    """
    Vision-only card extraction.

    Returns:
        {
          "fields": {<field_name>: {<quality-enhanced field dict>}, ...},
          "image_rotation_degrees": int (0|90|180|270),
          "discovered_keys": [<keys not present in configured card_fields>],
        }
    """
    from app.config import GEMINI_VISION_MODEL
    from google.genai import types as genai_types

    model = model or GEMINI_VISION_MODEL
    log_debug("=== GEMINI VISION EXTRACTION START ===", {"model": model, "image_path": image_path}, service="gemini_vision")

    client = get_gemini_client()
    prompt = render_streamlined_prompt(card_fields, valid_majors)

    with open(image_path, "rb") as f:
        image_data = f.read()
    mime_type = _mime_for(image_path)

    try:
        response = retry_with_exponential_backoff(
            func=lambda: client.models.generate_content(
                model=model,
                contents=[
                    prompt,
                    genai_types.Part.from_bytes(data=image_data, mime_type=mime_type),
                ],
                config=genai_types.GenerateContentConfig(
                    thinking_config={"thinking_budget": 0},
                ),
            ),
            max_retries=3,
            operation_name="Gemini vision content generation",
            service="gemini_vision",
        )
    except Exception as e:
        log_debug(f"Failed to generate content with Gemini vision: {str(e)}", service="gemini_vision")
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        raise

    if not response or not response.text:
        err = Exception("No response from Gemini vision")
        import sentry_sdk
        sentry_sdk.capture_exception(err)
        raise err

    try:
        parsed = json.loads(_strip_fences(response.text))
    except json.JSONDecodeError as e:
        log_debug(f"Gemini vision returned non-JSON response: {str(e)}", {"raw": (response.text or "")[:500]}, service="gemini_vision")
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        raise ValueError(f"Gemini vision returned non-JSON response: {e}") from e

    if not isinstance(parsed, dict):
        parsed = {}

    # Pull the orientation meta out before parsing fields so it is not treated
    # as a card field. Check both before and after envelope normalization, since
    # a wrapped {"fields": {...}} response may place _meta at either level.
    rotation_degrees = _pop_rotation(parsed)
    parsed = _normalize_fields(parsed)
    rotation_degrees = rotation_degrees or _pop_rotation(parsed)

    # Reuse the existing parser so the output shape, confidence scoring, and
    # required-field review logic match the current pipeline exactly.
    placeholder_fields = _build_placeholder_fields(card_fields)
    enhanced_fields = parse_gemini_quality_response(json.dumps(parsed), placeholder_fields)

    configured_keys = set(placeholder_fields.keys()) | {"mapped_major"}
    discovered_keys = [k for k in enhanced_fields.keys() if k not in configured_keys]
    if discovered_keys:
        log_debug("Vision path discovered unconfigured fields", {"keys": discovered_keys}, service="gemini_vision")

    log_debug("=== GEMINI VISION EXTRACTION COMPLETE ===", {
        "field_count": len(enhanced_fields),
        "rotation_degrees": rotation_degrees,
        "discovered_count": len(discovered_keys),
    }, service="gemini_vision")

    return {
        "fields": enhanced_fields,
        "image_rotation_degrees": rotation_degrees,
        "discovered_keys": discovered_keys,
    }


def _load_rotated_jpeg(local_image_path: str, degrees: int, max_dim: int = None) -> bytes:
    """Open an image, rotate it CLOCKWISE by `degrees`, optionally downscale, return JPEG bytes."""
    from PIL import Image

    with Image.open(local_image_path) as img:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        rotated = img.rotate(-degrees, expand=True) if degrees % 360 else img.copy()
        if max_dim:
            rotated.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        rotated.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue()


def verify_orientation(image_bytes: bytes, model: str = None) -> int:
    """
    Second-pass orientation check. Given an image that has already had the
    first-pass rotation applied, return the ADDITIONAL clockwise degrees
    (0/90/180/270) still needed to make it upright. This is a small, cheap call
    that mainly exists to catch the occasional 180 flip from the first pass.

    Returns 0 on any failure (keep the first-pass result).
    """
    from app.config import GEMINI_VISION_MODEL
    from google.genai import types as genai_types

    model = model or GEMINI_VISION_MODEL
    client = get_gemini_client()
    prompt = (
        "This is a scanned student inquiry card. Reply with ONLY a JSON object "
        '{"rotation_needed": N} where N is the additional CLOCKWISE degrees '
        "(0, 90, 180, or 270) required to make the card read normally upright with "
        "its printed text left-to-right. 0 means it already reads normally; 180 means "
        "it is upside down. Use the printed labels and logo as your guide. No other text."
    )
    try:
        response = retry_with_exponential_backoff(
            func=lambda: client.models.generate_content(
                model=model,
                contents=[prompt, genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")],
                config=genai_types.GenerateContentConfig(thinking_config={"thinking_budget": 0}),
            ),
            max_retries=2,
            operation_name="Gemini orientation verification",
            service="gemini_vision",
        )
        val = int((json.loads(_strip_fences(response.text or "")) or {}).get("rotation_needed", 0) or 0) % 360
        return val if val in _VALID_ROTATIONS else 0
    except Exception as e:
        log_debug(f"Orientation verification failed, keeping first pass: {e}", service="gemini_vision")
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        return 0


def apply_orientation_correction(local_image_path: str, first_pass_degrees: int, original_storage_path: str) -> dict:
    """
    Orchestrate orientation correction: take the first-pass rotation from the
    main extraction, verify it with a cheap second pass (which catches the 180
    flip), then save the upright image to storage.

    The verification only runs when the first pass is non-zero, so upright cards
    pay no extra cost.
    """
    info = {
        "first_pass_degrees": first_pass_degrees,
        "verification_additional": 0,
        "applied_degrees": first_pass_degrees if first_pass_degrees else 0,
        "uploaded": False,
    }
    if not first_pass_degrees or first_pass_degrees % 360 == 0:
        info["applied_degrees"] = 0
        return info

    try:
        rotated_preview = _load_rotated_jpeg(local_image_path, first_pass_degrees, max_dim=1024)
        additional = verify_orientation(rotated_preview)
    except Exception as e:
        log_debug(f"Orientation verify step errored, using first pass only: {e}", service="gemini_vision")
        additional = 0

    total = (first_pass_degrees + additional) % 360
    info["verification_additional"] = additional
    info["applied_degrees"] = total
    if total:
        info["uploaded"] = save_orientation_corrected_image(local_image_path, total, original_storage_path)
    log_debug("Orientation correction applied", info, service="gemini_vision")
    return info


def save_orientation_corrected_image(local_image_path: str, rotation_degrees: int, original_storage_path: str) -> bool:
    """
    Rotate the image to upright and overwrite the stored file so the review
    modal displays it correctly. Replaces the rotation re-save that the DocAI
    Enterprise OCR step used to perform (docai_service.py:179-227).

    image_rotation_degrees is the CLOCKWISE rotation needed to make the card
    upright. PIL rotate() is counter-clockwise, so we rotate by -degrees.

    Returns True if a corrected image was uploaded, False otherwise (including
    when no rotation is needed).
    """
    if not rotation_degrees or rotation_degrees % 360 == 0:
        return False
    if not original_storage_path:
        log_debug("No original_storage_path; skipping orientation re-save", service="gemini_vision")
        return False

    from PIL import Image

    try:
        with Image.open(local_image_path) as img:
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            corrected = img.rotate(-rotation_degrees, expand=True)

            buffer = io.BytesIO()
            corrected.save(buffer, format="JPEG", quality=90, optimize=True)
            corrected_content = buffer.getvalue()
    except Exception as e:
        log_debug(f"Failed to rotate image for orientation correction: {str(e)}", service="gemini_vision")
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        return False

    # Clean the storage path the same way the DocAI path did.
    if original_storage_path.startswith("cards-uploads/"):
        clean_path = original_storage_path.replace("cards-uploads/", "", 1)
    else:
        clean_path = original_storage_path

    try:
        supabase = get_supabase_client()
        if not supabase:
            raise Exception("Could not get Supabase client")

        try:
            supabase.storage.from_("cards-uploads").remove([clean_path])
        except Exception:
            pass

        supabase.storage.from_("cards-uploads").upload(
            path=clean_path,
            file=corrected_content,
            file_options={"content-type": "image/jpeg"},
        )
        log_debug(f"Saved orientation-corrected image ({rotation_degrees} deg) to {clean_path}", service="gemini_vision")
        return True
    except Exception as e:
        log_debug(f"Failed to save orientation-corrected image: {str(e)}", service="gemini_vision")
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        return False
