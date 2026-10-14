"""
Rule-based decision provider.

Baseline router that scores models using a weighted combination of
quality, cost, latency, and preference signals. This is the fallback
when Jev is unavailable and the default for testing/comparison.

Scoring formula:
    score = quality_w * quality
          - cost_w * normalized_cost
          - latency_w * normalized_latency
          + preference_w * preference_match

This is a starting heuristic, not a proven optimal formula.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.registry.schemas import DeploymentType, ModelEntry
from app.router.analyzer import QueryFeatures
from app.router.decision_provider import (
    DecisionProvider,
    DecisionResult,
    ModelScore,
)
from app.schemas.api import ChatPreferences, RoutingPriority, TaskCategory

logger = get_logger("rule_based_router")

# Weight presets by routing priority
_WEIGHT_PRESETS: dict[RoutingPriority, dict[str, float]] = {
    RoutingPriority.quality: {
        "quality": 0.60,
        "cost": 0.10,
        "latency": 0.10,
        "preference": 0.20,
    },
    RoutingPriority.balanced: {
        "quality": 0.35,
        "cost": 0.25,
        "latency": 0.20,
        "preference": 0.20,
    },
    RoutingPriority.speed: {
        "quality": 0.15,
        "cost": 0.15,
        "latency": 0.50,
        "preference": 0.20,
    },
    RoutingPriority.cost: {
        "quality": 0.15,
        "cost": 0.55,
        "latency": 0.10,
        "preference": 0.20,
    },
}

# Task-model affinity bonuses (heuristic, not benchmark-proven)
_TASK_AFFINITY: dict[TaskCategory, dict[str, float]] = {
    TaskCategory.coding: {
        "anthropic": 0.10,
        "openai": 0.05,
    },
    TaskCategory.creative: {
        "anthropic": 0.08,
        "google": 0.05,
    },
    TaskCategory.math: {
        "google": 0.08,
        "openai": 0.05,
    },
    TaskCategory.analysis: {
        "anthropic": 0.05,
        "google": 0.05,
    },
}


class RuleBasedDecisionProvider(DecisionProvider):
    """
    Baseline rule-based router.

    Uses normalized quality/cost/latency signals with
    configurable weight presets per routing priority.
    """

    @property
    def provider_name(self) -> str:
        return "rule_based"

    async def decide(
        self,
        features: QueryFeatures,
        candidates: list[ModelEntry],
        preferences: ChatPreferences,
    ) -> DecisionResult:
        if not candidates:
            return DecisionResult(
                reason="No candidates available",
                decision_provider=self.provider_name,
            )

        weights = _WEIGHT_PRESETS[preferences.priority]

        # Collect known values for normalization
        known_costs = [
            _estimate_cost(m, features)
            for m in candidates
            if _estimate_cost(m, features) is not None
        ]
        known_latencies = [
            m.estimated_latency_ms
            for m in candidates
            if m.estimated_latency_ms is not None
        ]

        max_cost = max(known_costs) if known_costs else 1.0
        max_latency = max(known_latencies) if known_latencies else 1.0

        # Prevent division by zero
        max_cost = max(max_cost, 1e-9)
        max_latency = max(max_latency, 1e-9)

        scores: list[ModelScore] = []
        for model in candidates:
            score_info = _score_model(
                model, features, preferences, weights,
                max_cost, max_latency,
            )
            scores.append(score_info)

        # Sort by score descending
        scores.sort(key=lambda s: s.score, reverse=True)

        best = scores[0]
        second_best_score = scores[1].score if len(scores) > 1 else 0.0

        # Confidence: how much better the top choice is than the runner-up
        score_gap = best.score - second_best_score
        confidence = min(1.0, max(0.0, score_gap / max(abs(best.score), 0.01)))

        result = DecisionResult(
            scores=scores,
            selected_model_id=best.model_id,
            confidence=confidence,
            reason=best.reason,
            decision_provider=self.provider_name,
        )

        logger.info(
            "Rule-based decision: selected=%s score=%.3f confidence=%.2f reason=%s",
            best.model_id,
            best.score,
            confidence,
            best.reason,
        )

        return result


def _score_model(
    model: ModelEntry,
    features: QueryFeatures,
    preferences: ChatPreferences,
    weights: dict[str, float],
    max_cost: float,
    max_latency: float,
) -> ModelScore:
    """Score a single model candidate."""

    # Quality component (0-1, default 0.5 for unknown)
    quality = model.quality_estimate if model.quality_estimate is not None else 0.5
    quality_component = quality

    # Cost component (0-1, normalized; unknown = 0.5 penalty)
    cost_raw = _estimate_cost(model, features)
    if cost_raw is not None:
        cost_component = cost_raw / max_cost
    else:
        # Unknown cost penalized moderately — not zero, not maximum
        cost_component = 0.5

    # Latency component (0-1, normalized; unknown = 0.5 penalty)
    if model.estimated_latency_ms is not None:
        latency_component = model.estimated_latency_ms / max_latency
    else:
        latency_component = 0.5

    # Preference component — task affinity bonus
    preference_component = 0.0
    affinities = _TASK_AFFINITY.get(features.task_category, {})
    preference_component += affinities.get(model.provider, 0.0)

    # Bonus for local models when local_only is preferred
    if preferences.local_only and model.deployment_type == DeploymentType.self_hosted:
        preference_component += 0.1

    # Compute weighted score
    score = (
        weights["quality"] * quality_component
        - weights["cost"] * cost_component
        - weights["latency"] * latency_component
        + weights["preference"] * preference_component
    )

    # Build reason
    reason = _build_reason(model, features, preferences, score)

    return ModelScore(
        model_id=model.model_id,
        score=score,
        reason=reason,
        quality_component=quality_component,
        cost_component=cost_component,
        latency_component=latency_component,
        preference_component=preference_component,
    )


def _estimate_cost(model: ModelEntry, features: QueryFeatures) -> float | None:
    """Estimate request cost. Returns None if pricing is unknown."""
    if model.input_cost_per_million_tokens is None or model.output_cost_per_million_tokens is None:
        return None

    input_cost = (features.estimated_input_tokens / 1_000_000) * model.input_cost_per_million_tokens
    output_cost = (features.estimated_output_tokens / 1_000_000) * model.output_cost_per_million_tokens
    return input_cost + output_cost


def _build_reason(
    model: ModelEntry,
    features: QueryFeatures,
    preferences: ChatPreferences,
    score: float,
) -> str:
    """Build a human-readable routing explanation."""
    parts: list[str] = []

    # Quality note
    if model.quality_estimate is not None and model.quality_estimate >= 0.85:
        parts.append("high quality estimate")
    elif model.quality_estimate is not None and model.quality_estimate < 0.70:
        parts.append("moderate quality")

    # Cost note
    if model.input_cost_per_million_tokens is not None:
        if model.input_cost_per_million_tokens < 0.5:
            parts.append("cost-efficient")
        elif model.input_cost_per_million_tokens > 5.0:
            parts.append("premium pricing")

    # Latency note
    if model.estimated_latency_ms is not None:
        if model.estimated_latency_ms < 700:
            parts.append("fast response")
        elif model.estimated_latency_ms > 2000:
            parts.append("higher latency")

    # Task affinity
    affinities = _TASK_AFFINITY.get(features.task_category, {})
    if model.provider in affinities:
        parts.append(f"good fit for {features.task_category.value}")

    # Priority match
    if preferences.priority == RoutingPriority.cost and model.input_cost_per_million_tokens is not None:
        if model.input_cost_per_million_tokens < 1.0:
            parts.append("matches cost priority")
    elif preferences.priority == RoutingPriority.speed and model.estimated_latency_ms is not None:
        if model.estimated_latency_ms < 1000:
            parts.append("matches speed priority")

    if not parts:
        parts.append("balanced selection")

    return f"Selected {model.display_name}: " + ", ".join(parts)
