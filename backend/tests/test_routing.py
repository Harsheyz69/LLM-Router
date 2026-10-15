"""
Tests for the rule-based decision provider and routing policy.
"""

from __future__ import annotations

import pytest

from app.registry.schemas import DeploymentType, HealthStatus, ModelEntry
from app.router.analyzer import QueryFeatures
from app.router.constraints import FilterResult
from app.router.decision_provider import DecisionProvider, DecisionResult, ModelScore
from app.router.policy import RoutingError, RoutingPolicy
from app.router.rule_based_provider import RuleBasedDecisionProvider
from app.schemas.api import ChatPreferences, RoutingPriority, TaskCategory


# ─── Helpers ──────────────────────────────────────────────────


def _model(
    model_id: str,
    provider: str = "openai",
    quality: float | None = 0.8,
    input_cost: float | None = 1.0,
    output_cost: float | None = 2.0,
    latency: float | None = 1000,
    deployment: DeploymentType = DeploymentType.commercial_api,
    available: bool = True,
    enabled: bool = True,
    supports_tools: bool = True,
    supports_vision: bool = False,
    context_window: int | None = 128_000,
) -> ModelEntry:
    return ModelEntry(
        model_id=model_id,
        display_name=f"Test {model_id}",
        provider=provider,
        deployment_type=deployment,
        quality_estimate=quality,
        input_cost_per_million_tokens=input_cost,
        output_cost_per_million_tokens=output_cost,
        estimated_latency_ms=latency,
        available=available,
        enabled=enabled,
        supports_tools=supports_tools,
        supports_vision=supports_vision,
        context_window=context_window,
        health_status=HealthStatus.unknown,
    )


def _features(
    category: TaskCategory = TaskCategory.general,
    input_tokens: int = 100,
    output_tokens: int = 200,
) -> QueryFeatures:
    return QueryFeatures(
        task_category=category,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
    )


def _prefs(**kwargs) -> ChatPreferences:
    return ChatPreferences(**kwargs)


# ─── RuleBasedDecisionProvider Tests ──────────────────────────


class TestRuleBasedDecisionProvider:
    """Test the rule-based scoring and selection."""

    @pytest.mark.asyncio
    async def test_selects_highest_quality_with_quality_priority(self):
        provider = RuleBasedDecisionProvider()
        candidates = [
            _model("low", quality=0.5, input_cost=0.1, output_cost=0.2, latency=500),
            _model("high", quality=0.95, input_cost=5.0, output_cost=10.0, latency=2000),
        ]
        result = await provider.decide(
            _features(), candidates, _prefs(priority=RoutingPriority.quality),
        )
        assert result.is_valid
        assert result.selected_model_id == "high"
        assert result.decision_provider == "rule_based"

    @pytest.mark.asyncio
    async def test_selects_cheapest_with_cost_priority(self):
        provider = RuleBasedDecisionProvider()
        candidates = [
            _model("cheap", quality=0.6, input_cost=0.1, output_cost=0.2, latency=800),
            _model("expensive", quality=0.9, input_cost=10.0, output_cost=20.0, latency=1500),
        ]
        result = await provider.decide(
            _features(), candidates, _prefs(priority=RoutingPriority.cost),
        )
        assert result.is_valid
        assert result.selected_model_id == "cheap"

    @pytest.mark.asyncio
    async def test_selects_fastest_with_speed_priority(self):
        provider = RuleBasedDecisionProvider()
        candidates = [
            _model("slow", quality=0.9, input_cost=1.0, output_cost=2.0, latency=5000),
            _model("fast", quality=0.7, input_cost=1.0, output_cost=2.0, latency=300),
        ]
        result = await provider.decide(
            _features(), candidates, _prefs(priority=RoutingPriority.speed),
        )
        assert result.is_valid
        assert result.selected_model_id == "fast"

    @pytest.mark.asyncio
    async def test_handles_unknown_cost(self):
        provider = RuleBasedDecisionProvider()
        candidates = [
            _model("known", quality=0.7, input_cost=1.0, output_cost=2.0),
            _model("unknown", quality=0.7, input_cost=None, output_cost=None),
        ]
        result = await provider.decide(
            _features(), candidates, _prefs(),
        )
        assert result.is_valid
        # Should still produce a valid result — unknown cost penalized at 0.5

    @pytest.mark.asyncio
    async def test_handles_unknown_latency(self):
        provider = RuleBasedDecisionProvider()
        candidates = [
            _model("known", quality=0.7, latency=1000),
            _model("unknown", quality=0.7, latency=None),
        ]
        result = await provider.decide(
            _features(), candidates, _prefs(),
        )
        assert result.is_valid

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        provider = RuleBasedDecisionProvider()
        result = await provider.decide(_features(), [], _prefs())
        assert not result.is_valid
        assert result.selected_model_id is None

    @pytest.mark.asyncio
    async def test_single_candidate(self):
        provider = RuleBasedDecisionProvider()
        candidates = [_model("only")]
        result = await provider.decide(_features(), candidates, _prefs())
        assert result.is_valid
        assert result.selected_model_id == "only"

    @pytest.mark.asyncio
    async def test_scores_are_ordered(self):
        provider = RuleBasedDecisionProvider()
        candidates = [
            _model("a", quality=0.5),
            _model("b", quality=0.7),
            _model("c", quality=0.9),
        ]
        result = await provider.decide(
            _features(), candidates, _prefs(priority=RoutingPriority.quality),
        )
        # Scores should be in descending order
        for i in range(len(result.scores) - 1):
            assert result.scores[i].score >= result.scores[i + 1].score

    @pytest.mark.asyncio
    async def test_confidence_between_0_and_1(self):
        provider = RuleBasedDecisionProvider()
        candidates = [_model("a", quality=0.5), _model("b", quality=0.9)]
        result = await provider.decide(_features(), candidates, _prefs())
        assert result.confidence is not None
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_task_affinity_influences_coding(self):
        """Anthropic should get a bonus for coding tasks."""
        provider = RuleBasedDecisionProvider()
        # Two models with identical base stats, different providers
        candidates = [
            _model("openai/m", provider="openai", quality=0.8, input_cost=1.0, output_cost=2.0, latency=1000),
            _model("anthropic/m", provider="anthropic", quality=0.8, input_cost=1.0, output_cost=2.0, latency=1000),
        ]
        result = await provider.decide(
            _features(category=TaskCategory.coding),
            candidates,
            _prefs(),
        )
        # Anthropic has higher coding affinity
        anthropic_score = next(s for s in result.scores if s.model_id == "anthropic/m")
        openai_score = next(s for s in result.scores if s.model_id == "openai/m")
        assert anthropic_score.score >= openai_score.score


# ─── RoutingPolicy Tests ─────────────────────────────────────


class FakeDecisionProvider(DecisionProvider):
    """A decision provider that returns a configurable result."""

    def __init__(self, result: DecisionResult | None = None, should_fail: bool = False):
        self._result = result
        self._should_fail = should_fail

    @property
    def provider_name(self) -> str:
        return "fake"

    async def decide(self, features, candidates, preferences) -> DecisionResult:
        if self._should_fail:
            raise RuntimeError("Fake decision provider failure")
        if self._result:
            return self._result
        # Default: pick the first candidate
        if candidates:
            return DecisionResult(
                scores=[ModelScore(model_id=candidates[0].model_id, score=1.0)],
                selected_model_id=candidates[0].model_id,
                confidence=0.9,
                reason="Fake decision",
                decision_provider="fake",
            )
        return DecisionResult(decision_provider="fake")


class FakeRegistry:
    """A fake model registry for testing."""

    def __init__(self, models: list[ModelEntry]):
        self._models = {m.model_id: m for m in models}

    def get_all(self) -> list[ModelEntry]:
        return list(self._models.values())

    def get_available(self) -> list[ModelEntry]:
        return [m for m in self._models.values() if m.available and m.enabled]

    def get_by_id(self, model_id: str) -> ModelEntry | None:
        return self._models.get(model_id)

    def update_health(self, model_id: str, status: HealthStatus) -> None:
        if model_id in self._models:
            self._models[model_id].health_status = status

    def set_availability(self, model_id: str, available: bool) -> None:
        if model_id in self._models:
            self._models[model_id].available = available


class TestRoutingPolicy:
    """Test the full routing policy pipeline."""

    @pytest.mark.asyncio
    async def test_successful_routing(self):
        models = [
            _model("m1", quality=0.8),
            _model("m2", quality=0.9),
        ]
        policy = RoutingPolicy(
            decision_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry(models),
        )
        decision = await policy.route("Hello world", _prefs())
        assert decision.selected_model is not None
        assert decision.routing_overhead_ms > 0

    @pytest.mark.asyncio
    async def test_no_models_raises_error(self):
        policy = RoutingPolicy(
            decision_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry([]),
        )
        with pytest.raises(RoutingError) as exc_info:
            await policy.route("Hello", _prefs())
        assert exc_info.value.error_code == "no_models_available"

    @pytest.mark.asyncio
    async def test_all_filtered_raises_error(self):
        """All models fail hard constraints → clear error."""
        models = [
            _model("m1", available=False),
            _model("m2", enabled=False),
        ]
        policy = RoutingPolicy(
            decision_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry(models),
        )
        with pytest.raises(RoutingError) as exc_info:
            await policy.route("Hello", _prefs())
        assert exc_info.value.error_code == "no_compatible_model"

    @pytest.mark.asyncio
    async def test_decision_provider_failure_falls_back(self):
        """If the primary decision provider fails, fall back to rule-based."""
        models = [_model("m1"), _model("m2")]
        policy = RoutingPolicy(
            decision_provider=FakeDecisionProvider(should_fail=True),
            fallback_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry(models),
        )
        decision = await policy.route("Hello", _prefs())
        assert decision.selected_model is not None
        assert decision.fallback_used is True

    @pytest.mark.asyncio
    async def test_invalid_decision_falls_back(self):
        """If decision provider returns invalid result, fall back."""
        invalid_result = DecisionResult(decision_provider="fake")  # No selected_model_id
        models = [_model("m1")]
        policy = RoutingPolicy(
            decision_provider=FakeDecisionProvider(result=invalid_result),
            fallback_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry(models),
        )
        decision = await policy.route("Hello", _prefs())
        assert decision.selected_model is not None
        assert decision.fallback_used is True

    @pytest.mark.asyncio
    async def test_decision_selects_non_candidate_falls_back(self):
        """If decision provider selects a model not in candidates, re-select."""
        bogus_result = DecisionResult(
            scores=[ModelScore(model_id="bogus/model", score=1.0)],
            selected_model_id="bogus/model",
            confidence=0.9,
            reason="Bogus",
            decision_provider="fake",
        )
        models = [_model("m1")]
        policy = RoutingPolicy(
            decision_provider=FakeDecisionProvider(result=bogus_result),
            fallback_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry(models),
        )
        decision = await policy.route("Hello", _prefs())
        assert decision.selected_model.model_id == "m1"
        assert decision.fallback_used is True

    @pytest.mark.asyncio
    async def test_routing_info_serializable(self):
        models = [_model("m1")]
        policy = RoutingPolicy(
            decision_provider=RuleBasedDecisionProvider(),
            registry=FakeRegistry(models),
        )
        decision = await policy.route("Hello", _prefs())
        info = decision.to_routing_info()
        # Should serialize without error
        data = info.model_dump()
        assert data["selected_model"] == "m1"
        assert "routing_overhead_ms" in data

    @pytest.mark.asyncio
    async def test_get_fallback_model_excludes_specified(self):
        models = [_model("m1"), _model("m2"), _model("m3")]
        policy = RoutingPolicy(registry=FakeRegistry(models))
        fallback = policy.get_fallback_model(models, exclude_model_id="m1")
        assert fallback is not None
        assert fallback.model_id != "m1"

    @pytest.mark.asyncio
    async def test_get_fallback_model_none_when_exhausted(self):
        models = [_model("m1")]
        policy = RoutingPolicy(registry=FakeRegistry(models))
        fallback = policy.get_fallback_model(models, exclude_model_id="m1")
        assert fallback is None
