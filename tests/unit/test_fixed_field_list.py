"""
Tests that a school's card_fields list is the only source of field keys.

- The requirements enhancer drops keys the school hasn't configured (junk like
  first_name_2 or email_someone@gmail.com) but keeps system keys and aliases.
- Universal cards (serial number) are left alone.
- The streamlined prompt forbids new keys and passes card_label/options hints.
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.core.streamlined_prompt import render_streamlined_prompt
from app.pipeline.enhancers.field_requirements import FieldRequirementsEnhancer, drop_unconfigured_fields
from app.pipeline.models import FieldData, PipelineContext

pytestmark = pytest.mark.unit

REQUIREMENTS = {
    "first_name": {"enabled": True, "required": True},
    "email": {"enabled": True, "required": True},
    "student_type": {"enabled": True, "required": False},
    "phone": {"enabled": True, "required": False},
}

JUNK_KEYS = ["first_name_2", "email_someone@gmail.com", "date_of_birth_02_07_09", "major_social_work"]


def _fields(keys):
    return {k: FieldData(value="x") for k in keys}


def _context(metadata=None):
    return PipelineContext(
        school_id="school",
        user_id="user",
        event_id=None,
        image_path="card.jpg",
        field_requirements=REQUIREMENTS,
        metadata=metadata or {},
    )


def test_drop_unconfigured_fields_keeps_configured_system_and_alias_keys():
    keys = ["first_name", "email", "cell", "mapped_major", "ceeb_code", "last_name"] + JUNK_KEYS
    result = drop_unconfigured_fields(_fields(keys), REQUIREMENTS)
    # "phone" is configured and canonicalizes to "cell", so cell survives
    assert set(result) == {"first_name", "email", "cell", "mapped_major", "ceeb_code", "last_name"}


def test_enhancer_drops_junk_keys_from_school_cards():
    result = FieldRequirementsEnhancer().enhance(_fields(["first_name", "email"] + JUNK_KEYS), _context())
    assert not set(JUNK_KEYS) & set(result)
    # Missing enabled fields are still added as blanks for the review form
    assert "student_type" in result


def test_enhancer_leaves_universal_cards_alone():
    context = _context({"serial_number": "ABC123"})
    result = FieldRequirementsEnhancer().enhance(_fields(["first_name", "entry_term"]), context)
    assert "entry_term" in result


def test_prompt_forbids_new_keys_and_includes_hints():
    card_fields = [
        {"key": "intended_sport", "enabled": True, "field_type": "text", "card_label": "What sport do you play?"},
        {"key": "student_type", "enabled": True, "field_type": "select", "options": ["Freshman", "Transfer"]},
        {"key": "hidden", "enabled": False},
        {"key": "review_only", "enabled": True, "field_type": "select", "options": ["A", "B"], "extract": False},
    ]
    prompt = render_streamlined_prompt(card_fields, ["Business"])
    assert 'intended_sport [text] (printed on card as "What sport do you play?")' in prompt
    assert "student_type [select: Freshman, Transfer]" in prompt
    assert "- hidden" not in prompt
    assert "- review_only" not in prompt
    assert "Never create a new key" in prompt
    assert "ADDITIONAL FIELDS" not in prompt
