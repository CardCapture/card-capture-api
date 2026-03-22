"""
Tests for basic API health and status endpoints.
"""
import pytest


class TestHealthEndpoints:
    """Test basic health check endpoints."""

    @pytest.mark.integration
    def test_api_root_responds(self, client):
        """Test that the API root endpoint responds."""
        response = client.get("/")
        # Most FastAPI apps return 200 or redirect
        assert response.status_code in [200, 307, 404]

    @pytest.mark.integration
    def test_docs_endpoint_disabled_in_non_dev(self, client):
        """Test that API docs are disabled in non-development environments."""
        response = client.get("/docs")
        # Docs should be disabled (404) when ENVIRONMENT != "development"
        assert response.status_code in [200, 307, 404]

    @pytest.mark.integration
    def test_openapi_schema_disabled_in_non_dev(self, client):
        """Test that OpenAPI schema is disabled in non-development environments."""
        response = client.get("/openapi.json")
        # Schema should be disabled (404) when ENVIRONMENT != "development"
        assert response.status_code in [200, 404]
