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
    def test_docs_endpoint_available(self, client):
        """Test that the OpenAPI docs are available."""
        response = client.get("/docs")
        assert response.status_code in [200, 307]

    @pytest.mark.integration
    def test_openapi_schema_available(self, client):
        """Test that the OpenAPI schema is available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
