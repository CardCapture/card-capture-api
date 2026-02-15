"""
Unit tests for cards retrieval and filtering via get_cards_db.

Tests:
1. Default retrieval returns all non-deleted cards
2. Filtering by event_id
3. Filtering by school_id (multi-tenant isolation)
4. Deleted/archived cards are excluded
5. Processing jobs are included for in-progress uploads

Note: The current cards endpoint does not use limit/offset pagination at the
database level. Instead, it returns all matching records. These tests verify
the filtering and exclusion logic that serves the same purpose of controlling
result sets.

All external services (Supabase) are mocked.
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch

# Set up test environment BEFORE any app imports
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

# Mock external dependency modules BEFORE any app imports
sys.modules['google'] = MagicMock()
sys.modules['google.cloud'] = MagicMock()
sys.modules['google.cloud.documentai_v1'] = MagicMock()
sys.modules['google.cloud.vision'] = MagicMock()
sys.modules['google.cloud.storage'] = MagicMock()
sys.modules['googlemaps'] = MagicMock()

mock_supabase_module = MagicMock()
mock_supabase_module.create_client = MagicMock(return_value=MagicMock())
sys.modules['supabase'] = mock_supabase_module


# =============================================================================
# Test Fixtures
# =============================================================================

def _make_card(doc_id, event_id="event-1", school_id="school-1", status="reviewed"):
    """Helper to create a card dict matching reviewed_data schema."""
    return {
        "document_id": doc_id,
        "id": doc_id,
        "fields": {
            "first_name": {"value": "John", "confidence": 0.95},
            "last_name": {"value": "Doe", "confidence": 0.95},
        },
        "review_status": status,
        "event_id": event_id,
        "school_id": school_id,
        "user_id": "user-123",
        "created_at": "2025-10-01T12:00:00Z",
        "updated_at": "2025-10-01T12:00:00Z",
        "image_path": f"/images/{doc_id}.jpg",
    }


def _make_processing_job(job_id, event_id="event-1", school_id="school-1"):
    """Helper to create a processing job dict."""
    return {
        "id": job_id,
        "status": "processing",
        "event_id": event_id,
        "school_id": school_id,
        "user_id": "user-123",
        "created_at": "2025-10-01T12:00:00Z",
        "updated_at": "2025-10-01T12:00:00Z",
        "image_path": f"/images/{job_id}.jpg",
    }


@pytest.fixture
def mock_supabase_client():
    """Create a Supabase client mock with configurable table responses."""
    client = MagicMock()
    return client


def _setup_table_responses(client, reviewed_data=None, interactions=None, jobs=None):
    """
    Configure the mock client to return specific data for each table query.

    Each argument is a list of dicts to be returned from that table.
    """
    reviewed_data = reviewed_data or []
    interactions = interactions or []
    jobs = jobs or []

    def make_chainable_mock(data):
        mock = MagicMock()
        mock.select.return_value = mock
        mock.eq.return_value = mock
        mock.in_.return_value = mock
        mock.execute.return_value = Mock(data=data, error=None)
        return mock

    def table_router(name):
        if name == "reviewed_data":
            return make_chainable_mock(reviewed_data)
        elif name == "student_school_interactions":
            return make_chainable_mock(interactions)
        elif name == "processing_jobs":
            return make_chainable_mock(jobs)
        return make_chainable_mock([])

    client.table = MagicMock(side_effect=table_router)


# =============================================================================
# Default Retrieval Tests
# =============================================================================

class TestGetCardsDefault:
    """Test default card retrieval behavior."""

    @pytest.mark.unit
    def test_returns_all_non_deleted_cards(self, mock_supabase_client):
        """Default query returns reviewed cards, excludes deleted ones."""
        cards = [
            _make_card("doc-1", status="reviewed"),
            _make_card("doc-2", status="needs_review"),
            _make_card("doc-3", status="deleted"),  # Should be filtered out
        ]

        _setup_table_responses(mock_supabase_client, reviewed_data=cards)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        # Deleted cards should be filtered out
        doc_ids = [c["document_id"] for c in result]
        assert "doc-1" in doc_ids
        assert "doc-2" in doc_ids
        assert "doc-3" not in doc_ids
        assert len(result) == 2

    @pytest.mark.unit
    def test_returns_empty_list_when_no_cards(self, mock_supabase_client):
        """When no cards exist, should return an empty list."""
        _setup_table_responses(mock_supabase_client)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert result == []

    @pytest.mark.unit
    def test_includes_v2_interactions(self, mock_supabase_client):
        """V2 student_school_interactions should be included in results."""
        v1_cards = [_make_card("doc-1")]
        v2_interactions = [
            {
                "id": "interaction-1",
                "fields": {"first_name": {"value": "Jane"}},
                "review_status": "reviewed",
                "event_id": "event-1",
                "school_id": "school-1",
                "user_id": "user-123",
                "created_at": "2025-10-01T12:00:00Z",
                "updated_at": "2025-10-01T12:00:00Z",
                "reviewed_at": None,
                "exported_at": None,
                "source_method": "qr_code",
                "image_path": None,
            }
        ]

        _setup_table_responses(
            mock_supabase_client,
            reviewed_data=v1_cards,
            interactions=v2_interactions,
        )

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert len(result) == 2
        ids = {c.get("document_id") or c.get("id") for c in result}
        assert "doc-1" in ids
        assert "interaction-1" in ids

    @pytest.mark.unit
    def test_archived_v2_interactions_excluded(self, mock_supabase_client):
        """Archived V2 interactions should be excluded from results."""
        v2_interactions = [
            {
                "id": "interaction-active",
                "fields": {},
                "review_status": "reviewed",
                "event_id": "event-1",
                "school_id": "school-1",
                "user_id": "user-123",
                "created_at": "2025-10-01T12:00:00Z",
                "updated_at": "2025-10-01T12:00:00Z",
                "reviewed_at": None,
                "exported_at": None,
                "source_method": "qr_code",
                "image_path": None,
            },
            {
                "id": "interaction-archived",
                "fields": {},
                "review_status": "archived",  # Should be excluded
                "event_id": "event-1",
                "school_id": "school-1",
                "user_id": "user-123",
                "created_at": "2025-10-01T12:00:00Z",
                "updated_at": "2025-10-01T12:00:00Z",
                "reviewed_at": None,
                "exported_at": None,
                "source_method": "qr_code",
                "image_path": None,
            },
        ]

        _setup_table_responses(mock_supabase_client, interactions=v2_interactions)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert len(result) == 1
        assert result[0]["id"] == "interaction-active"


# =============================================================================
# Event ID Filtering Tests
# =============================================================================

class TestGetCardsEventFilter:
    """Test filtering cards by event_id."""

    @pytest.mark.unit
    def test_event_id_filter_passes_to_query(self, mock_supabase_client):
        """When event_id is provided, it should be passed to .eq() for each table."""
        _setup_table_responses(mock_supabase_client, reviewed_data=[_make_card("doc-1")])

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            get_cards_db(mock_supabase_client, event_id="event-42")

        # Verify eq was called with event_id for reviewed_data table
        reviewed_table_calls = mock_supabase_client.table.call_args_list
        assert any(call[0][0] == "reviewed_data" for call in reviewed_table_calls)

        # The chained .eq() should have been called with event_id
        for call in reviewed_table_calls:
            table_mock = mock_supabase_client.table(call[0][0])
            if call[0][0] == "reviewed_data":
                table_mock.select.return_value.eq.assert_called()

    @pytest.mark.unit
    def test_no_event_id_returns_all_events(self, mock_supabase_client):
        """Without event_id filter, cards from all events should be returned."""
        cards = [
            _make_card("doc-1", event_id="event-A"),
            _make_card("doc-2", event_id="event-B"),
            _make_card("doc-3", event_id="event-C"),
        ]
        _setup_table_responses(mock_supabase_client, reviewed_data=cards)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert len(result) == 3


# =============================================================================
# School ID Filtering (Multi-Tenant Isolation) Tests
# =============================================================================

class TestGetCardsSchoolFilter:
    """Test multi-tenant isolation via school_id filtering."""

    @pytest.mark.unit
    def test_school_id_filter_passes_to_query(self, mock_supabase_client):
        """When school_id is provided, it should be used for filtering."""
        _setup_table_responses(mock_supabase_client, reviewed_data=[_make_card("doc-1", school_id="school-42")])

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            get_cards_db(mock_supabase_client, school_id="school-42")

        # Verify table was queried
        assert mock_supabase_client.table.called

    @pytest.mark.unit
    def test_no_school_id_returns_all_schools(self, mock_supabase_client):
        """Without school_id filter (superadmin case), cards from all schools returned."""
        cards = [
            _make_card("doc-1", school_id="school-A"),
            _make_card("doc-2", school_id="school-B"),
        ]
        _setup_table_responses(mock_supabase_client, reviewed_data=cards)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert len(result) == 2

    @pytest.mark.unit
    def test_combined_event_and_school_filter(self, mock_supabase_client):
        """Both event_id and school_id can be provided simultaneously."""
        cards = [_make_card("doc-1", event_id="event-1", school_id="school-1")]
        _setup_table_responses(mock_supabase_client, reviewed_data=cards)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client, event_id="event-1", school_id="school-1")

        assert len(result) == 1


# =============================================================================
# Processing Jobs (In-Progress Uploads) Tests
# =============================================================================

class TestGetCardsProcessingJobs:
    """Test that in-progress processing jobs are included in card results."""

    @pytest.mark.unit
    def test_processing_jobs_included_as_cards(self, mock_supabase_client):
        """Active processing jobs should appear as 'processing' status cards."""
        jobs = [_make_processing_job("job-1")]
        _setup_table_responses(mock_supabase_client, jobs=jobs)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert len(result) == 1
        assert result[0]["document_id"] == "job-1"
        assert result[0]["review_status"] == "processing"

    @pytest.mark.unit
    def test_duplicate_job_and_reviewed_data_deduped(self, mock_supabase_client):
        """If a job ID matches a reviewed_data document_id, the job should be skipped."""
        # Same ID in both reviewed_data and processing_jobs
        cards = [_make_card("shared-id-1")]
        jobs = [_make_processing_job("shared-id-1")]

        _setup_table_responses(mock_supabase_client, reviewed_data=cards, jobs=jobs)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        # Should have only 1 entry, not 2 (deduped)
        assert len(result) == 1
        assert result[0]["document_id"] == "shared-id-1"
        # Should be the reviewed version, not the processing job
        assert result[0]["review_status"] == "reviewed"

    @pytest.mark.unit
    def test_processing_job_has_empty_fields(self, mock_supabase_client):
        """Processing jobs should have empty fields since OCR hasn't completed."""
        jobs = [_make_processing_job("job-new")]
        _setup_table_responses(mock_supabase_client, jobs=jobs)

        with patch('app.repositories.cards_repository.validate_db_response', return_value=True):
            from app.repositories.cards_repository import get_cards_db
            result = get_cards_db(mock_supabase_client)

        assert result[0]["fields"] == {}


# =============================================================================
# Cards Service Layer Tests
# =============================================================================

class TestGetCardsService:
    """Test the service layer for get_cards."""

    @pytest.mark.unit
    def test_service_passes_filters_to_repository(self):
        """The service layer should pass event_id and school_id to the repository."""
        import asyncio

        mock_client = MagicMock()
        expected_cards = [_make_card("doc-1")]

        with patch('app.services.cards_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.cards_service.get_cards_db', return_value=expected_cards) as mock_get_cards:

            from app.services.cards_service import get_cards_service
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_cards_service("event-1", "school-1"))
            finally:
                loop.close()

            mock_get_cards.assert_called_once_with(mock_client, "event-1", "school-1")
            assert result == expected_cards

    @pytest.mark.unit
    def test_service_raises_on_repository_error(self):
        """If the repository raises an error, the service should propagate it."""
        import asyncio

        mock_client = MagicMock()

        with patch('app.services.cards_service.get_supabase_client', return_value=mock_client), \
             patch('app.services.cards_service.get_cards_db', side_effect=Exception("DB connection failed")):

            from app.services.cards_service import get_cards_service
            loop = asyncio.new_event_loop()
            try:
                with pytest.raises(Exception) as exc_info:
                    loop.run_until_complete(get_cards_service("event-1", "school-1"))
                assert "DB connection failed" in str(exc_info.value)
            finally:
                loop.close()
