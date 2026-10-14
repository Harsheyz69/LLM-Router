"""
Hard-constraint filter.

Deterministic application code that removes models that cannot satisfy
mandatory requirements. Applied BEFORE the decision layer and routing policy.

Hard constraints are pass/fail — not weighted preferences.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.registry.schemas import DeploymentType, HealthStatus, ModelEntry
from app.router.analyzer import QueryFeatures
from app.schemas.api import ChatPreferences

logger = get_logger("constraints")


@dataclass
class FilterResult:
    """Result of hard-constraint filtering."""
    candidates: list[ModelEntry] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (model_id, reason)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def has_candidates(self) -> bool:
        return len(self.candidates) > 0


def apply_hard_constraints(
    models: list[ModelEntry],
    features: QueryFeatures,
    preferences: ChatPreferences,
) -> FilterResult:
    """
    Filter models by mandatory requirements.

    Returns only models that pass ALL hard constraints.
    Each rejected model is annotated with the reason for rejection.
    """
    result = FilterResult()

    for model in models:
        rejection_reason = _check_model(model, features, preferences)
        if rejection_reason:
            result.rejected.append((model.model_id, rejection_reason))
        else:
            result.candidates.append(model)

    logger.info(
        "Hard-constraint filter: %d models in, %d candidates, %d rejected",
        len(models),
        result.candidate_count,
        len(result.rejected),
    )

    if result.rejected:
        logger.debug(
            "Rejected models: %s",
            "; ".join(f"{mid}: {reason}" for mid, reason in result.rejected),
        )

    return result


def _check_model(
    model: ModelEntry,
    features: QueryFeatures,
    preferences: ChatPreferences,
) -> str | None:
    """
    Check a single model against hard constraints.

    Returns None if the model passes, or a rejection reason string.
    """
    # 1. Must be enabled
    if not model.enabled:
        return "model disabled"

    # 2. Must be available (provider key configured or local runtime reachable)
    if not model.available:
        return "model unavailable (provider not configured)"

    # 3. Must not be unhealthy
    if model.health_status == HealthStatus.unhealthy:
        return "model unhealthy"

    # 4. Local-only preference
    if preferences.local_only and model.deployment_type == DeploymentType.commercial_api:
        return "commercial API excluded by local_only preference"

    # 5. Modality support
    if features.requires_vision and not model.supports_vision:
        return "vision not supported"

    # 6. Tool/function calling support
    if features.requires_tools and not model.supports_tools:
        return "tool calling not supported"

    # 7. Context window — must fit the estimated input + output
    if model.context_window is not None:
        required_context = features.estimated_total_tokens
        if required_context > model.context_window:
            return (
                f"context window too small "
                f"({model.context_window} < {required_context} estimated tokens)"
            )

    # 8. Budget ceiling — check against known pricing
    if preferences.max_cost_per_request is not None:
        estimated_cost = _estimate_request_cost(model, features)
        if estimated_cost is not None and estimated_cost > preferences.max_cost_per_request:
            return (
                f"estimated cost ${estimated_cost:.4f} exceeds "
                f"budget ${preferences.max_cost_per_request:.4f}"
            )
        # If cost is unknown, we do NOT reject — unknown cost != exceeds budget.
        # The routing policy may deprioritize unknown-cost models.

    return None  # Passes all constraints


def _estimate_request_cost(model: ModelEntry, features: QueryFeatures) -> float | None:
    """
    Estimate the cost of a request for a model.

    Returns None if pricing is unknown.
    """
    if model.input_cost_per_million_tokens is None or model.output_cost_per_million_tokens is None:
        return None

    input_cost = (features.estimated_input_tokens / 1_000_000) * model.input_cost_per_million_tokens
    output_cost = (features.estimated_output_tokens / 1_000_000) * model.output_cost_per_million_tokens

    return input_cost + output_cost
