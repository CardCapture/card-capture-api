"""
Tests for the split-name export fallback.

A combined name field (ACU's parent_guardian_name) was split into first/last.
Cards scanned before the split only carry the combined value, so exports fill
the split columns from it instead of writing blanks.
"""
import pytest

from app.utils.field_utils import (
    SPLIT_NAME_FALLBACKS,
    resolve_split_name_value,
    split_full_name,
)

pytestmark = pytest.mark.unit


class TestSplitFullName:
    def test_two_part_name(self):
        assert split_full_name("Karen Wild") == {"first_name": "Karen", "last_name": "Wild"}

    def test_single_word_is_a_first_name(self):
        assert split_full_name("Karen") == {"first_name": "Karen", "last_name": ""}

    def test_multi_word_surname_stays_intact(self):
        assert split_full_name("Ana De La Cruz") == {
            "first_name": "Ana",
            "last_name": "De La Cruz",
        }

    def test_extra_whitespace_is_ignored(self):
        assert split_full_name("  Karen   Wild  ") == {
            "first_name": "Karen",
            "last_name": "Wild",
        }

    @pytest.mark.parametrize("value", ["", "   ", None, 42, {"value": "Karen Wild"}])
    def test_non_string_and_empty_values_are_safe(self, value):
        assert split_full_name(value) == {"first_name": "", "last_name": ""}


class TestResolveSplitNameValue:
    def test_prefers_the_split_field(self):
        fields = {
            "parent_guardian_first_name": {"value": "Kathryn"},
            "parent_guardian_name": {"value": "Karen Wild"},
        }
        assert resolve_split_name_value(fields, "parent_guardian_first_name") == "Kathryn"

    def test_falls_back_to_the_combined_field(self):
        fields = {"parent_guardian_name": {"value": "Karen Wild"}}

        assert resolve_split_name_value(fields, "parent_guardian_first_name") == "Karen"
        assert resolve_split_name_value(fields, "parent_guardian_last_name") == "Wild"

    def test_handles_bare_string_field_values(self):
        fields = {"parent_guardian_name": "Karen Wild"}

        assert resolve_split_name_value(fields, "parent_guardian_first_name") == "Karen"
        assert resolve_split_name_value(fields, "parent_guardian_last_name") == "Wild"

    def test_returns_blank_when_nothing_is_present(self):
        assert resolve_split_name_value({}, "parent_guardian_first_name") == ""
        assert resolve_split_name_value({}, "parent_guardian_last_name") == ""

    def test_blank_split_field_still_falls_back(self):
        fields = {
            "parent_guardian_last_name": {"value": ""},
            "parent_guardian_name": {"value": "Karen Wild"},
        }
        assert resolve_split_name_value(fields, "parent_guardian_last_name") == "Wild"

    def test_non_dict_fields_are_safe(self):
        assert resolve_split_name_value(None, "parent_guardian_first_name") == ""

    def test_every_fallback_key_resolves(self):
        fields = {"parent_guardian_name": {"value": "Karen Wild"}}
        for key in SPLIT_NAME_FALLBACKS:
            assert resolve_split_name_value(fields, key)
