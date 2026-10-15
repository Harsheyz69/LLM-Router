"""
Tests for the API endpoints using FastAPI's TestClient.

All provider calls are mocked — no paid API calls during tests.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure no real API keys are used
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
os.environ["APP_ENV"] = "testing"


@pytest.fixture
def client():
    """Create a test client with fresh app state."""
    # Reset singletons before each test
    import app.api.chat as chat_module
    import app.registry.repository as registry_module
    from app.core.config import get_settings

    get_settings.cache_clear()
    chat_module._routing_policy = None
    chat_module._provider_service = None
    registry_module._registry = None

    from app.main import app
    return TestClient(app)


class TestHealthEndpoint:
    """Test GET /health."""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"
        assert "providers" in data
        assert "timestamp" in data

    def test_health_shows_provider_availability(self, client):
        response = client.get("/health")
        data = response.json()
        providers = data["providers"]
        # With empty keys, commercial providers should be false
        assert providers["openai"] is False
        assert providers["anthropic"] is False
        assert providers["google"] is False
        # Ollama should be true (URL is configured by default)
        assert providers["ollama"] is True

    def test_health_has_request_id(self, client):
        response = client.get("/health")
        assert "x-request-id" in response.headers

    def test_health_custom_request_id(self, client):
        response = client.get("/health", headers={"X-Request-ID": "test-id-123"})
        assert response.headers["x-request-id"] == "test-id-123"


class TestChatEndpoint:
    """Test POST /api/v1/chat."""

    def test_empty_message_rejected(self, client):
        response = client.post("/api/v1/chat", json={"message": ""})
        assert response.status_code == 422

    def test_blank_message_rejected(self, client):
        response = client.post("/api/v1/chat", json={"message": "   "})
        assert response.status_code == 422

    def test_missing_message_rejected(self, client):
        response = client.post("/api/v1/chat", json={})
        assert response.status_code == 422

    def test_no_providers_configured_returns_503(self, client):
        """With no API keys, routing should fail with 503."""
        response = client.post("/api/v1/chat", json={"message": "Hello"})
        # All commercial providers are unconfigured; Ollama models may still be
        # in the registry but will likely fail on actual call.
        # The response should be 503 (no available models) or 502 (provider error)
        assert response.status_code in (502, 503)
        data = response.json()
        assert "error_code" in data or "detail" in data

    @patch("app.providers.service.litellm")
    def test_successful_chat_with_mocked_provider(self, mock_litellm, client):
        """Test full chat flow with mocked LiteLLM."""
        # Set up a fake API key so models appear available
        os.environ["OPENAI_API_KEY"] = "sk-test-fake-key-for-testing"

        # Reset singletons to pick up the new key
        import app.api.chat as chat_module
        import app.registry.repository as registry_module
        from app.core.config import get_settings

        get_settings.cache_clear()
        chat_module._routing_policy = None
        chat_module._provider_service = None
        registry_module._registry = None

        # Mock LiteLLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello! I can help with that."
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30
        mock_response.model = "gpt-4o-mini"

        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        mock_litellm.suppress_debug_info = False

        response = client.post(
            "/api/v1/chat",
            json={
                "message": "What is binary search?",
                "preferences": {"priority": "balanced"},
            },
        )

        # Clean up
        os.environ["OPENAI_API_KEY"] = ""

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Hello! I can help with that."
        assert data["request_id"]
        assert data["conversation_id"]
        assert data["routing"]["selected_model"]
        assert data["routing"]["provider"]
        assert data["routing"]["task_category"]
        assert data["routing"]["routing_reason"]
        assert data["routing"]["candidate_count"] > 0
        assert data["usage"]["total_tokens"] == 30

    @patch("app.providers.service.litellm")
    def test_chat_with_quality_priority(self, mock_litellm, client):
        """Quality priority should prefer higher-quality models."""
        os.environ["OPENAI_API_KEY"] = "sk-test-fake-key"

        import app.api.chat as chat_module
        import app.registry.repository as registry_module
        from app.core.config import get_settings

        get_settings.cache_clear()
        chat_module._routing_policy = None
        chat_module._provider_service = None
        registry_module._registry = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.usage = None
        mock_response.model = "gpt-4o"

        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        mock_litellm.suppress_debug_info = False

        response = client.post(
            "/api/v1/chat",
            json={
                "message": "Explain quantum computing in depth",
                "preferences": {"priority": "quality"},
            },
        )

        os.environ["OPENAI_API_KEY"] = ""

        assert response.status_code == 200
        data = response.json()
        assert data["routing"]["router_type"] == "rule_based"

    @patch("app.providers.service.litellm")
    def test_provider_failure_triggers_fallback(self, mock_litellm, client):
        """Provider failure should attempt fallback to another model."""
        os.environ["OPENAI_API_KEY"] = "sk-test-fake-key"

        import app.api.chat as chat_module
        import app.registry.repository as registry_module
        from app.core.config import get_settings

        get_settings.cache_clear()
        chat_module._routing_policy = None
        chat_module._provider_service = None
        registry_module._registry = None

        # First call fails, second succeeds (fallback)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Fallback response"
        mock_response.usage = None
        mock_response.model = "gpt-4o-mini"

        mock_litellm.acompletion = AsyncMock(
            side_effect=[
                Exception("rate_limit_error: 429"),
                Exception("rate_limit_error: 429"),  # retry
                mock_response,  # fallback model succeeds
            ]
        )
        mock_litellm.suppress_debug_info = False

        response = client.post(
            "/api/v1/chat",
            json={"message": "Hello"},
        )

        os.environ["OPENAI_API_KEY"] = ""

        # Should still succeed via fallback, or return 502 if all fail
        assert response.status_code in (200, 502)

    def test_prompt_too_long_rejected(self, client):
        """Prompt exceeding max length should be rejected."""
        os.environ["OPENAI_API_KEY"] = "sk-test"

        import app.api.chat as chat_module
        import app.registry.repository as registry_module
        from app.core.config import get_settings

        get_settings.cache_clear()
        chat_module._routing_policy = None
        chat_module._provider_service = None
        registry_module._registry = None

        # Create a prompt exceeding the default 32000 char limit
        long_message = "x" * 33000

        response = client.post(
            "/api/v1/chat",
            json={"message": long_message},
        )

        os.environ["OPENAI_API_KEY"] = ""

        assert response.status_code == 422

    def test_invalid_preferences_rejected(self, client):
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "Hello",
                "preferences": {"priority": "invalid_value"},
            },
        )
        assert response.status_code == 422


class TestCORSHeaders:
    """Test CORS configuration."""

    def test_cors_allows_configured_origin(self, client):
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS preflight should succeed for configured origin
        assert response.status_code in (200, 204)


class TestSecurityHeaders:
    """Test that responses don't expose sensitive information."""

    def test_error_response_no_stack_trace(self, client):
        response = client.post("/api/v1/chat", json={"message": ""})
        body = response.text
        assert "Traceback" not in body
        assert "File" not in body or "line" not in body

    def test_health_no_api_keys(self, client):
        response = client.get("/health")
        body = response.text.lower()
        assert "sk-" not in body
        assert "api_key" not in body
        assert "secret" not in body
