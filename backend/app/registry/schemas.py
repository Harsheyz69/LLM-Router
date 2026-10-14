"""
Model registry schemas.

Defines the metadata structure for each model entry.
Unknown pricing or capabilities are represented as None, never as zero.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DeploymentType(str, Enum):
    commercial_api = "commercial_api"
    hosted_open_model = "hosted_open_model"
    self_hosted = "self_hosted"


class HealthStatus(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    unknown = "unknown"


class ModelEntry(BaseModel):
    """
    A single model in the registry.

    Fields with None indicate unknown values — not zero, not unsupported.
    """

    model_id: str = Field(
        description="Stable internal ID, typically 'provider/model-name'",
    )
    display_name: str = Field(description="Human-readable model name")
    provider: str = Field(description="openai | anthropic | google | ollama | vllm | other")
    deployment_type: DeploymentType
    license_label: str = Field(
        default="unknown",
        description="Verified license identifier or 'proprietary'",
    )

    # Capabilities
    modalities: list[str] = Field(
        default_factory=lambda: ["text"],
        description="Supported modalities: text, image, audio, etc.",
    )
    context_window: Optional[int] = Field(
        default=None,
        description="Maximum context length in tokens. None = unknown.",
    )
    supports_tools: bool = Field(default=False)
    supports_streaming: bool = Field(default=True)
    supports_vision: bool = Field(default=False)

    # Pricing — None means unknown, NOT free
    input_cost_per_million_tokens: Optional[float] = Field(
        default=None,
        description="Cost per 1M input tokens in USD. None = unknown.",
    )
    output_cost_per_million_tokens: Optional[float] = Field(
        default=None,
        description="Cost per 1M output tokens in USD. None = unknown.",
    )

    # Performance estimates
    estimated_latency_ms: Optional[float] = Field(
        default=None,
        description="Estimated typical latency in ms. None = unknown.",
    )
    quality_estimate: Optional[float] = Field(
        default=None,
        description="Relative quality score 0.0-1.0. None = unknown. Not a proven benchmark.",
    )

    # Availability
    available: bool = Field(default=True, description="Model is reachable/configured")
    health_status: HealthStatus = Field(default=HealthStatus.unknown)
    enabled: bool = Field(default=True, description="Model is enabled for routing")

    # Metadata
    metadata_version: int = Field(default=1)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    notes: str = Field(default="", description="License or deployment notes")

    # LiteLLM model string (may differ from model_id)
    litellm_model: Optional[str] = Field(
        default=None,
        description="Model string to pass to LiteLLM. If None, uses model_id.",
    )

    @property
    def effective_litellm_model(self) -> str:
        """The model string to use with LiteLLM."""
        return self.litellm_model or self.model_id
