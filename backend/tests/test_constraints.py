"""
Tests for hard-constraint filtering.
"""

from __future__ import annotations

import pytest

from app.registry.schemas import DeploymentType, HealthStatus, ModelEntry
from app.router.analyzer import QueryFeatures
from app.router.constraints import apply_hard_constraints
from app.schemas.api import ChatPreferences, RoutingPriority, TaskCategory


def _make_model(
    model_id: str = "test/model",
    provider: str = "openai",
    available: bool = True,
    enabled: bool = True,
    context_window: int | None = 128_000,
    supports_vision: bool = False,
    supports_tools: bool = True,
    supports_streaming: bool = True,
    health_status: HealthStatus = HealthStatus.unknown,
    deployment_type: DeploymentType = DeploymentType.commercial_api,
    input_cost: float | None = 1.0,
    output_cost: float | None = 2.0,
    quality: float | None = 0.8,
) -> ModelEntry:
    """Helper to create a model entry for testing."""
    return ModelEntry(
        model_id=model_id,
        display_name=f"Test {model_id}",
        provider=provider,
        deployment_type=deployment_type,
        context_window=context_window,
        supports_vision=supports_vision,
        supports_tools=supports_tools,
        supports_streaming=supports_streaming,
        health_status=health_status,
        available=available,
        enabled=enabled,
        input_cost_per_million_tokens=input_cost,
        output_cost_per_million_tokens=output_cost,
        quality_estimate=quality,
    )


def _make_features(
    input_tokens: int = 100,
    output_tokens: int = 200,
    requires_vision: bool = False,
    requires_tools: bool = False,
    category: TaskCategory = TaskCategory.general,
) -> QueryFeatures:
    """Helper to create query features for testing."""
    return QueryFeatures(
        task_category=category,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        requires_vision=requires_vision,
        requires_tools=requires_tools,
    )


def _default_prefs(**kwargs) -> ChatPreferences:
    return ChatPreferences(**kwargs)


class TestHardConstraintFilter:
    """Test deterministic hard-constraint filtering."""

    def test_all_pass(self):
        models = [_make_model("m1"), _make_model("m2")]
        features = _make_features()
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 2
        assert len(result.rejected) == 0

    def test_unavailable_model_rejected(self):
        models = [_make_model("m1", available=False)]
        features = _make_features()
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 0
        assert "unavailable" in result.rejected[0][1]

    def test_disabled_model_rejected(self):
        models = [_make_model("m1", enabled=False)]
        features = _make_features()
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 0
        assert "disabled" in result.rejected[0][1]

    def test_unhealthy_model_rejected(self):
        models = [_make_model("m1", health_status=HealthStatus.unhealthy)]
        features = _make_features()
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 0
        assert "unhealthy" in result.rejected[0][1]

    def test_vision_required_but_not_supported(self):
        models = [_make_model("m1", supports_vision=False)]
        features = _make_features(requires_vision=True)
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 0
        assert "vision" in result.rejected[0][1]

    def test_vision_required_and_supported(self):
        models = [_make_model("m1", supports_vision=True)]
        features = _make_features(requires_vision=True)
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 1

    def test_tools_required_but_not_supported(self):
        models = [_make_model("m1", supports_tools=False)]
        features = _make_features(requires_tools=True)
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 0

    def test_context_window_too_small(self):
        models = [_make_model("m1", context_window=100)]
        features = _make_features(input_tokens=500, output_tokens=500)
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 0
        assert "context window" in result.rejected[0][1]

    def test_context_window_unknown_passes(self):
        """Unknown context window should not reject — unknown != too small."""
        models = [_make_model("m1", context_window=None)]
        features = _make_features(input_tokens=500, output_tokens=500)
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 1

    def test_local_only_rejects_commercial(self):
        models = [
            _make_model("m1", deployment_type=DeploymentType.commercial_api),
            _make_model("m2", deployment_type=DeploymentType.self_hosted),
        ]
        features = _make_features()
        prefs = _default_prefs(local_only=True)
        result = apply_hard_constraints(models, features, prefs)
        assert result.candidate_count == 1
        assert result.candidates[0].model_id == "m2"

    def test_budget_ceiling_rejects_expensive(self):
        models = [
            _make_model("cheap", input_cost=0.1, output_cost=0.2),
            _make_model("expensive", input_cost=100.0, output_cost=200.0),
        ]
        features = _make_features(input_tokens=10000, output_tokens=10000)
        prefs = _default_prefs(max_cost_per_request=0.01)
        result = apply_hard_constraints(models, features, prefs)
        # Expensive model should be rejected
        assert all(c.model_id != "expensive" for c in result.candidates)

    def test_unknown_cost_not_rejected_by_budget(self):
        """Unknown cost must NOT be treated as exceeding budget."""
        models = [_make_model("m1", input_cost=None, output_cost=None)]
        features = _make_features()
        prefs = _default_prefs(max_cost_per_request=0.001)
        result = apply_hard_constraints(models, features, prefs)
        assert result.candidate_count == 1

    def test_mixed_filtering(self):
        """Multiple constraints applied together."""
        models = [
            _make_model("ok", supports_vision=True, context_window=200_000),
            _make_model("no_vision", supports_vision=False),
            _make_model("small_ctx", supports_vision=True, context_window=10),
            _make_model("disabled", supports_vision=True, enabled=False),
        ]
        features = _make_features(
            requires_vision=True,
            input_tokens=100,
            output_tokens=100,
        )
        result = apply_hard_constraints(models, features, _default_prefs())
        assert result.candidate_count == 1
        assert result.candidates[0].model_id == "ok"
        assert len(result.rejected) == 3

    def test_empty_model_list(self):
        result = apply_hard_constraints([], _make_features(), _default_prefs())
        assert result.candidate_count == 0
        assert not result.has_candidates
