"""
Tests for request validation and API schemas.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.api import (
    ChatPreferences,
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    HealthResponse,
    MessageRole,
    RoutingInfo,
    RoutingPriority,
    TaskCategory,
)


class TestChatRequest:
    """Test ChatRequest validation."""

    def test_valid_request(self):
        req = ChatRequest(message="Hello, world!")
        assert req.message == "Hello, world!"
        assert req.stream is False
        assert req.conversation_id is None
        assert req.preferences.priority == RoutingPriority.balanced

    def test_valid_request_with_all_fields(self):
        req = ChatRequest(
            conversation_id="conv-123",
            message="Write a Python function",
            preferences=ChatPreferences(
                priority=RoutingPriority.quality,
                local_only=True,
                max_cost_per_request=0.01,
            ),
            stream=True,
        )
        assert req.conversation_id == "conv-123"
        assert req.stream is True
        assert req.preferences.local_only is True
        assert req.preferences.max_cost_per_request == 0.01

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_blank_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="   ")

    def test_negative_budget_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                message="test",
                preferences=ChatPreferences(max_cost_per_request=-1.0),
            )

    def test_invalid_priority_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                message="test",
                preferences=ChatPreferences(priority="fastest"),  # type: ignore
            )


class TestChatResponse:
    """Test ChatResponse schema."""

    def test_valid_response(self):
        resp = ChatResponse(
            request_id="req-123",
            conversation_id="conv-456",
            message="Hello! How can I help?",
            routing=RoutingInfo(
                selected_model="openai/gpt-4o-mini",
                provider="openai",
                task_category=TaskCategory.general,
            ),
        )
        assert resp.request_id == "req-123"
        assert resp.role == MessageRole.assistant
        assert resp.routing.selected_model == "openai/gpt-4o-mini"


class TestErrorDetail:
    """Test ErrorDetail schema."""

    def test_error_detail(self):
        err = ErrorDetail(
            error_code="validation_error",
            message="Invalid input",
            request_id="req-789",
        )
        assert err.error_code == "validation_error"
        assert err.request_id == "req-789"
        assert err.details is None


class TestHealthResponse:
    """Test HealthResponse schema."""

    def test_health_response(self):
        resp = HealthResponse(
            providers={"openai": True, "anthropic": False},
        )
        assert resp.status == "ok"
        assert resp.providers["openai"] is True
        assert resp.providers["anthropic"] is False
