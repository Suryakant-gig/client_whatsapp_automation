"""Tests for application foundation and health check endpoint."""

import unittest

from app.api.routes.health import HealthResponse, get_health
from app.core.config import Settings, get_settings
from app.main import create_application


class TestHealthEndpoint(unittest.TestCase):
    """Test suite for application configuration and health endpoint."""

    def test_settings_load(self) -> None:
        """Test configuration module loads settings properly."""
        settings = get_settings()
        self.assertIsInstance(settings, Settings)
        self.assertEqual(settings.APP_NAME, "travel-agency-automation")
        self.assertEqual(settings.PORT, 8000)

    def test_health_endpoint_logic(self) -> None:
        """Test health check route returns expected structure and values."""
        response = get_health()
        self.assertIsInstance(response, HealthResponse)
        self.assertEqual(response.status, "healthy")
        self.assertEqual(response.application, "travel-agency-automation")

    def test_fastapi_app_created(self) -> None:
        """Test FastAPI application instance initializes and registers OpenAPI routes."""
        app = create_application()
        self.assertEqual(app.title, "travel-agency-automation")
        self.assertEqual(app.docs_url, "/docs")
        openapi_schema = app.openapi()
        self.assertIn("/health", openapi_schema["paths"])


if __name__ == "__main__":
    unittest.main()
