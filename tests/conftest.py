"""
Shared fixtures for all tests in the card-capture-api project.
"""
import pytest
import os
from unittest.mock import Mock, MagicMock, patch
from fastapi.testclient import TestClient

# Set test environment before importing app
os.environ["ENVIRONMENT"] = "test"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-key"
os.environ["SUPABASE_ANON_KEY"] = "test-anon-key"


# ============================================================================
# App & Client Fixtures
# ============================================================================

@pytest.fixture
def app():
    """Create FastAPI test app."""
    from app.main import app
    return app


@pytest.fixture
def client(app):
    """Create test client for API requests."""
    return TestClient(app)


# ============================================================================
# Authentication Fixtures
# ============================================================================

@pytest.fixture
def mock_current_user():
    """Mock authenticated user data."""
    return {
        "id": "test-user-123",
        "email": "test@example.com",
        "school_id": "test-school-123",
        "role": ["admin"],
    }


@pytest.fixture
def authenticated_client(client, mock_current_user):
    """Client with mocked authentication."""
    with patch('app.core.auth.get_current_user', return_value=mock_current_user):
        yield client


@pytest.fixture
def recruiter_client(client):
    """Client authenticated as a recruiter (non-admin)."""
    recruiter_user = {
        "id": "recruiter-user-123",
        "email": "recruiter@school.edu",
        "school_id": "test-school-123",
        "role": ["recruiter"],
    }
    with patch('app.core.auth.get_current_user', return_value=recruiter_user):
        yield client


# ============================================================================
# Database & Supabase Fixtures
# ============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for all tests."""
    with patch('app.core.clients.get_supabase_client') as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_supabase_table():
    """Helper to create chainable mock table queries."""
    class MockTableQuery:
        def __init__(self, data=None):
            self._data = data or []
            self._single = False

        def select(self, *args):
            return self

        def insert(self, data):
            self._data = data
            return self

        def update(self, data):
            self._data = data
            return self

        def upsert(self, data):
            self._data = data
            return self

        def delete(self):
            return self

        def eq(self, field, value):
            return self

        def neq(self, field, value):
            return self

        def in_(self, field, values):
            return self

        def is_(self, field, value):
            return self

        def order(self, field, **kwargs):
            return self

        def limit(self, count):
            return self

        def single(self):
            self._single = True
            return self

        def maybe_single(self):
            return self

        def execute(self):
            result = Mock()
            if self._single:
                result.data = self._data[0] if self._data else None
            else:
                result.data = self._data
            result.error = None
            return result

    return MockTableQuery


# ============================================================================
# External Service Mocks
# ============================================================================

@pytest.fixture
def mock_stripe():
    """Mock Stripe for payment tests."""
    with patch('stripe.billing_portal.Session.create') as mock_session:
        mock_session.return_value = Mock(url="https://billing.stripe.com/test")
        yield mock_session


@pytest.fixture
def mock_stripe_checkout():
    """Mock Stripe Checkout session creation."""
    with patch('stripe.checkout.Session.create') as mock_session:
        mock_session.return_value = Mock(
            id="cs_test_123",
            url="https://checkout.stripe.com/test"
        )
        yield mock_session


@pytest.fixture
def mock_resend():
    """Mock Resend email service."""
    with patch('resend.Emails.send') as mock_send:
        mock_send.return_value = {"id": "test-email-123"}
        yield mock_send


@pytest.fixture
def mock_docai():
    """Mock Google Document AI processing."""
    with patch('app.services.docai_service.process_image_with_docai') as mock:
        mock.return_value = (
            {
                'first_name': {'value': 'John', 'confidence': 0.9, 'source': 'docai'},
                'last_name': {'value': 'Doe', 'confidence': 0.9, 'source': 'docai'},
            },
            '/tmp/cropped.jpg'
        )
        yield mock


@pytest.fixture
def mock_gemini():
    """Mock Google Gemini AI processing."""
    with patch('app.services.gemini_service.process_card_with_gemini_v2') as mock:
        mock.return_value = {
            'first_name': {'value': 'John', 'confidence': 0.95, 'source': 'gemini'},
            'last_name': {'value': 'Doe', 'confidence': 0.95, 'source': 'gemini'},
            'email': {'value': 'john@example.com', 'confidence': 0.9, 'source': 'gemini'},
        }
        yield mock


@pytest.fixture
def mock_address_validation():
    """Mock Google Address Validation API."""
    with patch('app.services.address_validation_service.validate_address') as mock:
        mock.return_value = {
            'is_valid': True,
            'formatted_address': '123 Main St, Anytown, TX 12345',
            'components': {
                'street': '123 Main St',
                'city': 'Anytown',
                'state': 'TX',
                'zip_code': '12345',
            },
        }
        yield mock


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_card_data():
    """Sample card data for tests."""
    return {
        "id": "card-123",
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "cell": "5551234567",
        "high_school": "Central High School",
        "address": "123 Main St",
        "city": "Anytown",
        "state": "TX",
        "zip_code": "12345",
        "status": "reviewed",
        "school_id": "test-school-123",
        "event_id": "test-event-123",
        "user_id": "test-user-123",
    }


@pytest.fixture
def sample_event_data():
    """Sample event data for tests."""
    return {
        "id": "event-123",
        "name": "Fall College Fair 2025",
        "date": "2025-10-15",
        "location": "Convention Center",
        "school_id": "test-school-123",
        "status": "active",
    }


@pytest.fixture
def sample_user_data():
    """Sample user data for tests."""
    return {
        "id": "user-123",
        "email": "user@example.com",
        "first_name": "Test",
        "last_name": "User",
        "school_id": "test-school-123",
        "role": ["recruiter"],
    }


@pytest.fixture
def sample_school_data():
    """Sample school data for tests."""
    return {
        "id": "school-123",
        "name": "Test University",
        "domain": "test.edu",
        "subscription_status": "active",
        "settings": {
            "notify_on_scan": True,
            "require_mfa": False,
        },
    }


# ============================================================================
# File & Image Fixtures
# ============================================================================

@pytest.fixture
def temp_image_file(tmp_path):
    """Create a temporary image file for testing."""
    image_path = tmp_path / "test_card.jpg"
    # Write minimal JPEG data
    image_path.write_bytes(
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
        b'\xff\xd9'
    )
    return str(image_path)


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def freeze_time():
    """Fixture to freeze time for deterministic tests."""
    from datetime import datetime
    with patch('datetime.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2025, 3, 15, 12, 0, 0)
        mock_dt.utcnow.return_value = datetime(2025, 3, 15, 18, 0, 0)
        yield mock_dt
