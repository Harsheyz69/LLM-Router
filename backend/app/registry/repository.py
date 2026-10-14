"""
Model registry repository.

Provides access to the set of configured model entries.
Initial models are loaded from a verified static configuration.
Future: load from database or configuration file.

Only models with verified metadata and configured credentials
should be marked as available.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.registry.schemas import DeploymentType, HealthStatus, ModelEntry

logger = get_logger("registry")


def _build_default_models() -> list[ModelEntry]:
    """
    Return a verified set of model entries.

    Pricing and context windows are based on publicly available
    documentation as of 2024-2025. They may change — treat as estimates
    and update when new information is available.
    """
    return [
        # ── OpenAI ──────────────────────────────────────────
        ModelEntry(
            model_id="openai/gpt-4o",
            display_name="GPT-4o",
            provider="openai",
            deployment_type=DeploymentType.commercial_api,
            license_label="proprietary",
            modalities=["text", "image"],
            context_window=128_000,
            supports_tools=True,
            supports_streaming=True,
            supports_vision=True,
            input_cost_per_million_tokens=2.50,
            output_cost_per_million_tokens=10.00,
            estimated_latency_ms=1500,
            quality_estimate=0.90,
            litellm_model="gpt-4o",
            notes="OpenAI flagship multimodal model.",
        ),
        ModelEntry(
            model_id="openai/gpt-4o-mini",
            display_name="GPT-4o Mini",
            provider="openai",
            deployment_type=DeploymentType.commercial_api,
            license_label="proprietary",
            modalities=["text", "image"],
            context_window=128_000,
            supports_tools=True,
            supports_streaming=True,
            supports_vision=True,
            input_cost_per_million_tokens=0.15,
            output_cost_per_million_tokens=0.60,
            estimated_latency_ms=800,
            quality_estimate=0.75,
            litellm_model="gpt-4o-mini",
            notes="Cost-efficient OpenAI model.",
        ),

        # ── Anthropic ──────────────────────────────────────
        ModelEntry(
            model_id="anthropic/claude-sonnet-4-20250514",
            display_name="Claude Sonnet 4",
            provider="anthropic",
            deployment_type=DeploymentType.commercial_api,
            license_label="proprietary",
            modalities=["text", "image"],
            context_window=200_000,
            supports_tools=True,
            supports_streaming=True,
            supports_vision=True,
            input_cost_per_million_tokens=3.00,
            output_cost_per_million_tokens=15.00,
            estimated_latency_ms=2000,
            quality_estimate=0.92,
            litellm_model="anthropic/claude-sonnet-4-20250514",
            notes="Anthropic high-capability model.",
        ),
        ModelEntry(
            model_id="anthropic/claude-3-5-haiku-20241022",
            display_name="Claude 3.5 Haiku",
            provider="anthropic",
            deployment_type=DeploymentType.commercial_api,
            license_label="proprietary",
            modalities=["text"],
            context_window=200_000,
            supports_tools=True,
            supports_streaming=True,
            supports_vision=False,
            input_cost_per_million_tokens=0.80,
            output_cost_per_million_tokens=4.00,
            estimated_latency_ms=600,
            quality_estimate=0.72,
            litellm_model="anthropic/claude-3-5-haiku-20241022",
            notes="Fast, cost-efficient Anthropic model.",
        ),

        # ── Google Gemini ──────────────────────────────────
        ModelEntry(
            model_id="google/gemini-2.0-flash",
            display_name="Gemini 2.0 Flash",
            provider="google",
            deployment_type=DeploymentType.commercial_api,
            license_label="proprietary",
            modalities=["text", "image"],
            context_window=1_048_576,
            supports_tools=True,
            supports_streaming=True,
            supports_vision=True,
            input_cost_per_million_tokens=0.10,
            output_cost_per_million_tokens=0.40,
            estimated_latency_ms=500,
            quality_estimate=0.78,
            litellm_model="gemini/gemini-2.0-flash",
            notes="Google fast model with large context.",
        ),
        ModelEntry(
            model_id="google/gemini-2.5-pro",
            display_name="Gemini 2.5 Pro",
            provider="google",
            deployment_type=DeploymentType.commercial_api,
            license_label="proprietary",
            modalities=["text", "image"],
            context_window=1_048_576,
            supports_tools=True,
            supports_streaming=True,
            supports_vision=True,
            input_cost_per_million_tokens=1.25,
            output_cost_per_million_tokens=10.00,
            estimated_latency_ms=2500,
            quality_estimate=0.93,
            litellm_model="gemini/gemini-2.5-pro",
            notes="Google flagship reasoning model.",
        ),

        # ── Ollama (local, self-hosted) ────────────────────
        ModelEntry(
            model_id="ollama/llama3.2",
            display_name="Llama 3.2 (Ollama)",
            provider="ollama",
            deployment_type=DeploymentType.self_hosted,
            license_label="Llama 3.2 Community License",
            modalities=["text"],
            context_window=128_000,
            supports_tools=False,
            supports_streaming=True,
            supports_vision=False,
            input_cost_per_million_tokens=None,  # Self-hosted: infrastructure cost
            output_cost_per_million_tokens=None,
            estimated_latency_ms=None,  # Hardware-dependent
            quality_estimate=0.65,
            litellm_model="ollama/llama3.2",
            notes="Local inference via Ollama. Cost depends on hardware.",
        ),
        ModelEntry(
            model_id="ollama/qwen2.5",
            display_name="Qwen 2.5 (Ollama)",
            provider="ollama",
            deployment_type=DeploymentType.self_hosted,
            license_label="Apache 2.0",
            modalities=["text"],
            context_window=128_000,
            supports_tools=False,
            supports_streaming=True,
            supports_vision=False,
            input_cost_per_million_tokens=None,
            output_cost_per_million_tokens=None,
            estimated_latency_ms=None,
            quality_estimate=0.68,
            litellm_model="ollama/qwen2.5",
            notes="Local inference via Ollama. Apache 2.0 licensed.",
        ),
    ]


class ModelRegistry:
    """
    In-memory model registry.

    Loads models from static configuration and marks availability
    based on configured provider credentials.
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelEntry] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default models and update availability based on config."""
        settings = get_settings()
        models = _build_default_models()

        for model in models:
            # Mark availability based on whether the provider key is configured
            if model.provider == "openai":
                model.available = settings.has_provider_key("openai")
            elif model.provider == "anthropic":
                model.available = settings.has_provider_key("anthropic")
            elif model.provider == "google":
                model.available = settings.has_provider_key("google")
            elif model.provider == "ollama":
                # Ollama is assumed available if URL is configured;
                # actual health is checked at runtime
                model.available = bool(settings.ollama_base_url)
            else:
                model.available = False

            if model.available:
                model.health_status = HealthStatus.unknown
            else:
                model.health_status = HealthStatus.unhealthy

            self._models[model.model_id] = model

        available_count = sum(1 for m in self._models.values() if m.available)
        logger.info(
            "Model registry loaded: %d models total, %d available",
            len(self._models),
            available_count,
        )

    def get_all(self) -> list[ModelEntry]:
        """Return all registered models."""
        return list(self._models.values())

    def get_available(self) -> list[ModelEntry]:
        """Return models that are available and enabled."""
        return [
            m for m in self._models.values()
            if m.available and m.enabled
        ]

    def get_by_id(self, model_id: str) -> ModelEntry | None:
        """Look up a specific model by ID."""
        return self._models.get(model_id)

    def update_health(self, model_id: str, status: HealthStatus) -> None:
        """Update the health status of a model."""
        if model_id in self._models:
            self._models[model_id].health_status = status
            logger.info("Model %s health updated to %s", model_id, status.value)

    def set_availability(self, model_id: str, available: bool) -> None:
        """Mark a model as available or unavailable."""
        if model_id in self._models:
            self._models[model_id].available = available
            if not available:
                self._models[model_id].health_status = HealthStatus.unhealthy


# Singleton instance
_registry: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    """Get or create the singleton model registry."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
