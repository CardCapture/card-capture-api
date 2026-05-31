"""
Unit tests for the vision-only extraction service (DocAI removal path).

Covers:
- Pure helpers (fence stripping, envelope unwrap, placeholder build, mime, rotation).
- process_card_with_gemini_vision with a mocked Gemini client: prompt + image
  bytes are sent, orientation meta is parsed, discovered fields are reported,
  and a wrapped {"fields": {...}} envelope is unwrapped.
- save_orientation_corrected_image rotation + upload behavior.
"""
import json
import os
import sys
import types as _pytypes
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def stub_genai(monkeypatch):
    """
    Provide a stub google.genai.types so the vision service's in-function
    import succeeds regardless of test-ordering pollution (another test in the
    suite replaces sys.modules['google'] with a MagicMock that is not a real
    package). The Gemini client itself is mocked separately in each test.
    """
    types_mod = _pytypes.ModuleType("google.genai.types")
    types_mod.Part = MagicMock()
    types_mod.GenerateContentConfig = MagicMock()
    genai_mod = _pytypes.ModuleType("google.genai")
    genai_mod.types = types_mod
    google_mod = _pytypes.ModuleType("google")
    google_mod.genai = genai_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    # Neutralize the retry wrapper to a direct passthrough. These tests verify
    # parsing/orientation/discovery, not retry behavior, and other tests in the
    # suite pollute the retry helper's reference. Passthrough keeps the mocked
    # client's response deterministic.
    monkeypatch.setattr(svc, "retry_with_exponential_backoff", lambda func, **kwargs: func())
    return types_mod

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from app.services import gemini_vision_service as svc

pytestmark = pytest.mark.unit


CARD_FIELDS = [
    {"key": "first_name", "label": "First Name", "enabled": True, "required": True, "field_type": "text"},
    {"key": "last_name", "label": "Last Name", "enabled": True, "required": False, "field_type": "text"},
    {"key": "disabled_field", "label": "Disabled", "enabled": False, "required": False, "field_type": "text"},
]


def _field(value, ftype="text"):
    return {
        "value": value,
        "edit_made": False,
        "edit_type": "none",
        "original_value": value,
        "text_clarity": "clear",
        "certainty": "certain",
        "notes": "",
        "field_type": ftype,
        "detected_options": [],
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_strip_fences():
    assert svc._strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert svc._strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert svc._strip_fences('{"a": 1}') == '{"a": 1}'


def test_normalize_fields_unwraps_envelope():
    wrapped = {"fields": {"first_name": {"value": "Jane", "field_type": "text"}}}
    assert svc._normalize_fields(wrapped) == {"first_name": {"value": "Jane", "field_type": "text"}}


def test_normalize_fields_passthrough_flat():
    flat = {"first_name": {"value": "Jane", "field_type": "text"}}
    assert svc._normalize_fields(flat) == flat


def test_build_placeholder_fields_skips_keyless_and_keeps_flags():
    placeholder = svc._build_placeholder_fields(CARD_FIELDS)
    assert set(placeholder.keys()) == {"first_name", "last_name", "disabled_field"}
    assert placeholder["first_name"]["required"] is True
    assert placeholder["last_name"]["required"] is False
    assert placeholder["disabled_field"]["enabled"] is False


def test_mime_for():
    assert svc._mime_for("/tmp/card.jpg") == "image/jpeg"
    assert svc._mime_for("/tmp/card.png") == "image/png"
    assert svc._mime_for("/tmp/card.unknownext") == "image/jpeg"


def test_pop_rotation_valid_and_invalid():
    assert svc._pop_rotation({"_meta": {"image_rotation_degrees": 90}}) == 90
    assert svc._pop_rotation({"_meta": {"image_rotation_degrees": 360}}) == 0
    assert svc._pop_rotation({"_meta": {"image_rotation_degrees": 45}}) == 0  # out of range
    assert svc._pop_rotation({"_meta": {}}) == 0
    assert svc._pop_rotation({}) == 0


# ---------------------------------------------------------------------------
# process_card_with_gemini_vision
# ---------------------------------------------------------------------------

def _make_client(response_text):
    client = MagicMock()
    resp = MagicMock()
    resp.text = response_text
    client.models.generate_content.return_value = resp
    return client


def test_process_card_sends_prompt_and_image_and_parses(tmp_path, stub_genai):
    image_file = tmp_path / "card.jpg"
    image_file.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")

    response = json.dumps({
        "_meta": {"image_rotation_degrees": 90},
        "first_name": _field("Jane"),
        "last_name": _field("Doe"),
        "intended_sport": _field("Soccer"),  # discovered (not in card_fields)
    })
    client = _make_client(response)

    with patch.object(svc, "get_gemini_client", return_value=client):
        result = svc.process_card_with_gemini_vision(str(image_file), CARD_FIELDS, ["Business"])

    # generate_content called once with the streamlined prompt as first content
    client.models.generate_content.assert_called_once()
    _, kwargs = client.models.generate_content.call_args
    contents = kwargs["contents"]
    assert "Fields to extract" in contents[0]
    assert "first_name" in contents[0]

    # orientation parsed
    assert result["image_rotation_degrees"] == 90
    # configured fields present
    assert result["fields"]["first_name"]["value"] == "Jane"
    assert result["fields"]["last_name"]["value"] == "Doe"
    # discovered field reported and present
    assert result["discovered_keys"] == ["intended_sport"]
    assert "intended_sport" in result["fields"]


def test_process_card_unwraps_wrapped_envelope(tmp_path, stub_genai):
    image_file = tmp_path / "card.jpg"
    image_file.write_bytes(b"fakebytes")

    response = json.dumps({
        "_meta": {"image_rotation_degrees": 0},
        "fields": {
            "first_name": _field("Sam"),
        },
    })
    client = _make_client(response)

    with patch.object(svc, "get_gemini_client", return_value=client):
        result = svc.process_card_with_gemini_vision(str(image_file), CARD_FIELDS, [])

    assert result["fields"]["first_name"]["value"] == "Sam"
    assert result["image_rotation_degrees"] == 0


def test_process_card_raises_on_non_json(tmp_path, stub_genai):
    image_file = tmp_path / "card.jpg"
    image_file.write_bytes(b"fakebytes")
    client = _make_client("this is not json")

    with patch.object(svc, "get_gemini_client", return_value=client):
        with patch("sentry_sdk.capture_exception"):
            with pytest.raises(ValueError):
                svc.process_card_with_gemini_vision(str(image_file), CARD_FIELDS, [])


# ---------------------------------------------------------------------------
# save_orientation_corrected_image
# ---------------------------------------------------------------------------

def test_save_orientation_zero_is_noop(tmp_path):
    image_file = tmp_path / "card.jpg"
    image_file.write_bytes(b"fakebytes")
    # 0 degrees: no upload, returns False without touching supabase
    with patch.object(svc, "get_supabase_client") as mock_sb:
        assert svc.save_orientation_corrected_image(str(image_file), 0, "cards-uploads/x/y.jpg") is False
        mock_sb.assert_not_called()


def test_verify_orientation_parses_value(stub_genai):
    client = _make_client('{"rotation_needed": 180}')
    with patch.object(svc, "get_gemini_client", return_value=client):
        assert svc.verify_orientation(b"imgbytes") == 180


def test_verify_orientation_rejects_out_of_range(stub_genai):
    client = _make_client('{"rotation_needed": 45}')
    with patch.object(svc, "get_gemini_client", return_value=client):
        assert svc.verify_orientation(b"imgbytes") == 0


def test_apply_orientation_zero_first_pass_is_noop():
    with patch.object(svc, "verify_orientation") as vmock, \
         patch.object(svc, "save_orientation_corrected_image") as smock:
        info = svc.apply_orientation_correction("/tmp/x.jpg", 0, "cards-uploads/x.jpg")
    assert info["applied_degrees"] == 0
    vmock.assert_not_called()
    smock.assert_not_called()


def test_apply_orientation_verification_corrects_180_flip(tmp_path):
    from PIL import Image

    p = tmp_path / "card.jpg"
    Image.new("RGB", (100, 40), "white").save(str(p), "JPEG")

    # First pass said 90; verification finds it's still 180 off -> total 270.
    with patch.object(svc, "verify_orientation", return_value=180) as vmock, \
         patch.object(svc, "save_orientation_corrected_image", return_value=True) as smock:
        info = svc.apply_orientation_correction(str(p), 90, "cards-uploads/u/card.jpg")

    assert info["first_pass_degrees"] == 90
    assert info["verification_additional"] == 180
    assert info["applied_degrees"] == 270
    assert info["uploaded"] is True
    vmock.assert_called_once()
    smock.assert_called_once_with(str(p), 270, "cards-uploads/u/card.jpg")


def test_apply_orientation_verification_confirms_first_pass(tmp_path):
    from PIL import Image

    p = tmp_path / "card.jpg"
    Image.new("RGB", (100, 40), "white").save(str(p), "JPEG")

    # First pass 270 and verification agrees (0 additional) -> apply 270.
    with patch.object(svc, "verify_orientation", return_value=0), \
         patch.object(svc, "save_orientation_corrected_image", return_value=True) as smock:
        info = svc.apply_orientation_correction(str(p), 270, "cards-uploads/u/card.jpg")

    assert info["applied_degrees"] == 270
    smock.assert_called_once_with(str(p), 270, "cards-uploads/u/card.jpg")


def test_save_orientation_rotates_and_uploads(tmp_path):
    from PIL import Image

    # A non-square image so rotation is observable
    img = Image.new("RGB", (100, 40), color="white")
    image_file = tmp_path / "card.jpg"
    img.save(str(image_file), format="JPEG")

    mock_storage = MagicMock()
    mock_client = MagicMock()
    mock_client.storage.from_.return_value = mock_storage

    with patch.object(svc, "get_supabase_client", return_value=mock_client):
        ok = svc.save_orientation_corrected_image(str(image_file), 90, "cards-uploads/user/date/card.jpg")

    assert ok is True
    # path cleaned of bucket prefix
    mock_storage.upload.assert_called_once()
    _, kwargs = mock_storage.upload.call_args
    assert kwargs["path"] == "user/date/card.jpg"
    assert kwargs["file_options"]["content-type"] == "image/jpeg"
