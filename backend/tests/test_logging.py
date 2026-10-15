"""
Tests for logging and secret redaction.
"""

from __future__ import annotations

from app.core.logging import redact_secrets


class TestSecretRedaction:
    """Test that sensitive patterns are redacted from log output."""

    def test_redacts_openai_key(self):
        msg = "Using key sk-abc123def456ghi789jkl012mno345"
        result = redact_secrets(msg)
        assert "sk-abc123" not in result
        assert "[REDACTED]" in result

    def test_redacts_anthropic_key(self):
        msg = "Key is sk-ant-some-long-anthropic-key-value"
        result = redact_secrets(msg)
        assert "sk-ant-" not in result
        assert "[REDACTED]" in result

    def test_redacts_google_key(self):
        msg = "Google key: AIzaSomethingLongEnoughToMatch1234567890"
        result = redact_secrets(msg)
        assert "AIza" not in result
        assert "[REDACTED]" in result

    def test_redacts_bearer_token(self):
        msg = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test.payload"
        result = redact_secrets(msg)
        assert "eyJhbG" not in result
        assert "[REDACTED]" in result

    def test_redacts_api_key_assignment(self):
        msg = "api_key=sk-something-secret"
        result = redact_secrets(msg)
        assert "sk-something" not in result
        assert "[REDACTED]" in result

    def test_preserves_normal_text(self):
        msg = "Model gpt-4o selected for task analysis"
        result = redact_secrets(msg)
        assert result == msg

    def test_preserves_empty_string(self):
        assert redact_secrets("") == ""
