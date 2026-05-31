"""
Tests that the use_vision_only_extraction flag correctly branches _extract.

- Flag ON: DocAI is NOT called, the vision-only path IS called, and the result
  is tagged extraction_mode=vision_only.
- Flag OFF: the existing DocAI + Gemini path runs and the vision path is NOT
  called (production behavior preserved).
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

# Mock heavy external SDKs before importing the pipeline (matches repo pattern).
for _mod in ("google.cloud", "google.cloud.documentai_v1"):
    sys.modules.setdefault(_mod, MagicMock())

from app.pipeline.pipeline import CardProcessingPipeline
from app.pipeline.models import PipelineContext, ProcessingStage

pytestmark = pytest.mark.unit

CARD_FIELDS = [{"key": "first_name", "enabled": True, "required": True, "field_type": "text"}]


def _context():
    return PipelineContext(
        school_id="school-1",
        user_id="user-1",
        event_id=None,
        image_path="/tmp/card.jpg",
        original_storage_path="cards-uploads/user-1/2026/card.jpg",
        valid_majors=["Business"],
        field_requirements={},
    )


def test_flag_on_uses_vision_skips_docai(monkeypatch):
    pipeline = CardProcessingPipeline()
    monkeypatch.setattr(
        pipeline,
        "_get_school_extraction_settings",
        lambda school_id: ({"use_vision_only_extraction": True, "card_fields": CARD_FIELDS}, True),
    )

    vision_return = {
        "fields": {"first_name": {"value": "Jane", "source": "gemini", "enabled": True, "required": True}},
        "image_rotation_degrees": 0,
        "discovered_keys": [],
    }

    docai_mock = MagicMock()
    vision_mock = MagicMock(return_value=vision_return)

    with patch("app.pipeline.pipeline.process_image_with_docai", docai_mock), \
         patch("app.services.gemini_vision_service.process_card_with_gemini_vision", vision_mock), \
         patch("app.utils.image_processing.ensure_proper_orientation", lambda p: p):
        result = pipeline._extract("/tmp/card.jpg", _context())

    docai_mock.assert_not_called()
    vision_mock.assert_called_once()
    assert result.stage == ProcessingStage.EXTRACTION
    assert result.metadata["extraction_mode"] == "vision_only"
    assert "first_name" in result.fields
    assert result.fields["first_name"].value == "Jane"


def test_flag_off_uses_docai_skips_vision(monkeypatch):
    pipeline = CardProcessingPipeline()
    monkeypatch.setattr(
        pipeline,
        "_get_school_extraction_settings",
        lambda school_id: ({"use_vision_only_extraction": False, "docai_processor_id": None}, True),
    )

    # DocAI returns (fields, cropped_image_path, ocr_text, serial_number)
    docai_mock = MagicMock(return_value=({}, "/tmp/crop.jpg", "", None))
    gemini_v2_mock = MagicMock(return_value={})
    vision_mock = MagicMock()

    with patch("app.pipeline.pipeline.process_image_with_docai", docai_mock), \
         patch("app.pipeline.pipeline.process_card_with_gemini_v2", gemini_v2_mock), \
         patch("app.services.gemini_vision_service.process_card_with_gemini_vision", vision_mock):
        result = pipeline._extract("/tmp/card.jpg", _context())

    docai_mock.assert_called_once()
    vision_mock.assert_not_called()
    assert result.stage == ProcessingStage.EXTRACTION
    assert "extraction_mode" not in result.metadata
