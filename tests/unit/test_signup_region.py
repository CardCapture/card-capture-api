"""
Sign-up sheet rows have no reliable state, so school search and address lookup
prefer Mississippi and its neighbors. Inquiry cards must keep the old behavior.
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.core.signup_region import signup_state_search_order
from app.pipeline.enhancers import address_validator
from app.pipeline.enhancers.address_validator import AddressValidationEnhancer
from app.pipeline.enhancers.high_school_matcher import HighSchoolMatcherEnhancer
from app.pipeline.models import FieldData, PipelineContext

pytestmark = pytest.mark.unit


def _context(source=None):
    return PipelineContext(
        school_id="school", user_id="user", event_id=None, image_path="x.jpg",
        metadata={"source": source} if source else {},
    )


def _result(state, suggested_state=None):
    suggestion = {"city": "Somewhere", "state": suggested_state, "zip_code": "00000"} if suggested_state else None
    return SimpleNamespace(state=state, suggestion=suggestion, error=None)


def test_state_search_order_uses_real_row_state_first_and_skips_junk():
    assert signup_state_search_order("")[:2] == ["MS", "LA"]
    assert signup_state_search_order("tx")[:2] == ["TX", "MS"]
    assert signup_state_search_order("VIC")[0] == "MS"
    assert signup_state_search_order("LA").count("LA") == 1


def test_signup_street_accepts_home_state_match():
    with patch.object(address_validator, "validate_address", return_value=_result("verified", "MS")) as va:
        result = AddressValidationEnhancer()._validate_signup_street("112 Hursey Ave")
    assert result.suggestion["state"] == "MS"
    va.assert_called_once_with("112 Hursey Ave", "", "MS", "")


def test_signup_street_rejects_matches_outside_region():
    with patch.object(address_validator, "validate_address", return_value=_result("verified", "VIC")):
        result = AddressValidationEnhancer()._validate_signup_street("105 Greenwood Dr")
    assert result.state == "not_verified"
    assert result.suggestion is None


def test_cards_keep_normal_address_lookup():
    fields = {"address": FieldData(value="105 Greenwood Dr")}
    with patch.object(address_validator, "validate_address", return_value=_result("not_verified")) as va:
        AddressValidationEnhancer().enhance(fields, _context())
    va.assert_called_once_with("105 Greenwood Dr", "", "", "")


def test_matcher_prefers_region_only_for_signup_rows():
    enhancer = HighSchoolMatcherEnhancer()
    enhancer.matcher = MagicMock()
    enhancer.matcher.validate_and_enhance_high_school_with_location.side_effect = lambda f, **kw: f

    enhancer.enhance({"high_school": FieldData(value="Pass Christian")}, _context("signup_sheet"))
    signup_kwargs = enhancer.matcher.validate_and_enhance_high_school_with_location.call_args.kwargs
    assert signup_kwargs["preferred_states"][0] == "MS"

    enhancer.enhance({"high_school": FieldData(value="Pass Christian")}, _context())
    card_kwargs = enhancer.matcher.validate_and_enhance_high_school_with_location.call_args.kwargs
    assert card_kwargs["preferred_states"] is None
