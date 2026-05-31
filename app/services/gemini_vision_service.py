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
