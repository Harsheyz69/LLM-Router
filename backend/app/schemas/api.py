"""
Pydantic request and response schemas for the API.

These define the typed contract between frontend and backend.
Provider-specific details stay out of these schemas.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class RoutingPriority(str, Enum):
    """User preference for quality/cost/speed trade-off."""
    quality = "quality"
    balanced = "balanced"
    speed = "speed"
    cost = "cost"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class TaskCategory(str, Enum):
    """Detected task type for routing decisions."""
    general = "general"
    coding = "coding"
    creative = "creative"
    analysis = "analysis"
    math = "math"
    summarization = "summarization"
    translation = "translation"
    conversation = "conversation"


# ──────────────────────────────────────────────
# Request schemas
# ──────────────────────────────────────────────

class ChatPreferences(BaseModel):
    """User-configurable routing preferences."""
    priority: RoutingPriority = Field(default=RoutingPriority.balanced)
    local_only: bool = Field(default=False, description="Restrict to locally-served models only")
    max_cost_per_request: Optional[float] = Field(
        default=None,
        description="Hard budget ceiling per request in USD. None = no limit.",
        ge=0,
    )


class ChatRequest(BaseModel):
    """Incoming chat request from the frontend."""
    conversation_id: Optional[str] = Field(
        default=None,
        description="Existing conversation ID, or null for a new conversation",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=100_000,  # Will be further limited by config.max_prompt_length
        description="User's prompt text",
    )
    preferences: ChatPreferences = Field(default_factory=ChatPreferences)
    stream: bool = Field(default=False, description="Request streaming response")

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message must not be blank")
        return v


# ──────────────────────────────────────────────
# Response schemas
# ──────────────────────────────────────────────

class RoutingInfo(BaseModel):
    """Routing metadata returned to the frontend. No secrets or internal config."""
    selected_model: str = Field(description="Model ID that was selected")
    selected_model_display_name: str = Field(default="", description="Human-readable model name")
    provider: str = Field(description="Provider name")
    task_category: TaskCategory = Field(default=TaskCategory.general)
    routing_reason: str = Field(default="", description="Human-readable routing explanation")
    candidate_count: int = Field(default=0, description="Number of eligible candidates after filtering")
    fallback_used: bool = Field(default=False)
    routing_overhead_ms: Optional[float] = Field(default=None)
    estimated_cost: Optional[float] = Field(
        default=None,
        description="Estimated cost in USD, or null if unknown",
    )
    router_type: str = Field(default="rule_based", description="Which router made the decision")


class UsageInfo(BaseModel):
    """Token usage information when available."""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ChatResponse(BaseModel):
    """Non-streaming chat response."""
    request_id: str
    conversation_id: str
    message: str = Field(description="Assistant's response text")
    role: MessageRole = Field(default=MessageRole.assistant)
    routing: RoutingInfo
    usage: Optional[UsageInfo] = None
    latency_ms: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ErrorDetail(BaseModel):
    """Consistent error response format. Never contains stack traces or secrets."""
    error_code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Safe, user-facing error message")
    request_id: str = Field(default="")
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional safe context, if available",
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(default="ok")
    version: str = Field(default="0.1.0")
    environment: str = Field(default="development")
    providers: dict[str, bool] = Field(
        default_factory=dict,
        description="Provider availability (key configured, not necessarily healthy)",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────
# Streaming event schemas
# ──────────────────────────────────────────────

class StreamEvent(BaseModel):
    """Base streaming event."""
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class StreamMetaEvent(BaseModel):
    """First event in a stream — metadata."""
    request_id: str
    conversation_id: str


class StreamRoutingEvent(BaseModel):
    """Routing info event sent early in the stream."""
    routing: RoutingInfo


class StreamTokenEvent(BaseModel):
    """Incremental token event."""
    text: str


class StreamDoneEvent(BaseModel):
    """Terminal success event."""
    usage: Optional[UsageInfo] = None
    latency_ms: Optional[float] = None


class StreamErrorEvent(BaseModel):
    """Terminal error event."""
    error_code: str
    message: str
