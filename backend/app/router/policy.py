"""
Routing policy — the application-owned final model selector.

This module validates decision-layer output and makes the final selection.
The decision layer (Jev or rule-based) provides signals; the routing policy
decides. Jev must never bypass hard constraints.
"""

from __future__ import annotations

import time
from typing import Optional

from app.core.logging import get_logger
from app.registry.repository import ModelRegistry, get_model_registry
from app.registry.schemas import ModelEntry
from app.router.analyzer import QueryFeatures, analyze_query
from app.router.constraints import FilterResult, apply_hard_constraints
from app.router.decision_provider import DecisionProvider, DecisionResult
from app.router.rule_based_provider import RuleBasedDecisionProvider
from app.schemas.api import ChatPreferences, RoutingInfo, TaskCategory

logger = get_logger("policy")


class RoutingDecision:
    """Complete routing decision with all metadata."""

    def __init__(
        self,
        selected_model: ModelEntry,
        features: QueryFeatures,
        decision_result: DecisionResult,
        filter_result: FilterResult,
        routing_overhead_ms: float,
        fallback_used: bool = False,
    ):
        self.selected_model = selected_model
        self.features = features
        self.decision_result = decision_result
        self.filter_result = filter_result
        self.routing_overhead_ms = routing_overhead_ms
        self.fallback_used = fallback_used

    def to_routing_info(self) -> RoutingInfo:
        """Convert to the API response schema."""
        # Estimate cost for the selected model
        estimated_cost = None
        m = self.selected_model
        if m.input_cost_per_million_tokens is not None and m.output_cost_per_million_tokens is not None:
            estimated_cost = (
                (self.features.estimated_input_tokens / 1_000_000) * m.input_cost_per_million_tokens
                + (self.features.estimated_output_tokens / 1_000_000) * m.output_cost_per_million_tokens
            )

        return RoutingInfo(
            selected_model=self.selected_model.model_id,
            selected_model_display_name=self.selected_model.display_name,
            provider=self.selected_model.provider,
            task_category=self.features.task_category,
            routing_reason=self.decision_result.reason,
            candidate_count=self.filter_result.candidate_count,
            fallback_used=self.fallback_used,
            routing_overhead_ms=round(self.routing_overhead_ms, 1),
            estimated_cost=round(estimated_cost, 6) if estimated_cost is not None else None,
            router_type=self.decision_result.decision_provider,
        )


class RoutingPolicy:
    """
    Application-owned routing policy.

    Orchestrates: query analysis → registry → hard constraints → decision layer → final selection.
    """

    def __init__(
        self,
        decision_provider: Optional[DecisionProvider] = None,
        fallback_provider: Optional[DecisionProvider] = None,
        registry: Optional[ModelRegistry] = None,
    ):
        self._decision_provider = decision_provider or RuleBasedDecisionProvider()
        self._fallback_provider = fallback_provider or RuleBasedDecisionProvider()
        self._registry = registry or get_model_registry()

    async def route(
        self,
        message: str,
        preferences: ChatPreferences,
    ) -> RoutingDecision:
        """
        Execute the full routing pipeline.

        Raises RoutingError if no compatible model is found.
        """
        start = time.perf_counter()

        # Step 1: Analyze query
        features = analyze_query(message)

        # Step 2: Get available models from registry
        available_models = self._registry.get_available()
        if not available_models:
            raise RoutingError(
                "No models are currently available. "
                "Please configure at least one provider API key.",
                error_code="no_models_available",
            )

        # Step 3: Apply hard constraints
        filter_result = apply_hard_constraints(available_models, features, preferences)
        if not filter_result.has_candidates:
            raise RoutingError(
                "No compatible model found for this request. "
                "All available models were filtered out by your requirements.",
                error_code="no_compatible_model",
            )

        # Step 4: Get decision from decision layer
        fallback_used = False
        try:
            decision = await self._decision_provider.decide(
                features, filter_result.candidates, preferences,
            )
        except Exception as exc:
            logger.warning(
                "Decision provider failed (%s), falling back to rule-based: %s",
                self._decision_provider.provider_name,
                str(exc),
            )
            decision = await self._fallback_provider.decide(
                features, filter_result.candidates, preferences,
            )
            fallback_used = True

        # Step 5: Validate the decision
        if not decision.is_valid:
            logger.warning("Invalid decision result, falling back to rule-based")
            decision = await self._fallback_provider.decide(
                features, filter_result.candidates, preferences,
            )
            fallback_used = True

        # Step 6: Verify selected model is in the filtered candidates
        selected_model = self._validate_selection(
            decision.selected_model_id, filter_result.candidates,
        )
        if selected_model is None:
            # Decision layer returned a model that didn't pass hard constraints
            logger.warning(
                "Decision layer selected %s which is not in filtered candidates. "
                "Re-selecting from candidates.",
                decision.selected_model_id,
            )
            # Force selection from actual candidates
            decision = await self._fallback_provider.decide(
                features, filter_result.candidates, preferences,
            )
            fallback_used = True
            selected_model = self._validate_selection(
                decision.selected_model_id, filter_result.candidates,
            )
            if selected_model is None:
                raise RoutingError(
                    "Routing policy failed to select a valid model.",
                    error_code="routing_failure",
                )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return RoutingDecision(
            selected_model=selected_model,
            features=features,
            decision_result=decision,
            filter_result=filter_result,
            routing_overhead_ms=elapsed_ms,
            fallback_used=fallback_used,
        )

    def _validate_selection(
        self,
        model_id: str | None,
        candidates: list[ModelEntry],
    ) -> ModelEntry | None:
        """Verify the selected model is among filtered candidates."""
        if model_id is None:
            return None
        for candidate in candidates:
            if candidate.model_id == model_id:
                return candidate
        return None

    def get_fallback_model(
        self, candidates: list[ModelEntry], exclude_model_id: str | None = None,
    ) -> ModelEntry | None:
        """
        Get a fallback model from candidates, excluding a specific model.

        Used when the initially selected model fails at the provider level.
        """
        for candidate in candidates:
            if candidate.model_id != exclude_model_id:
                return candidate
        return None


class RoutingError(Exception):
    """Raised when routing cannot produce a valid selection."""

    def __init__(self, message: str, error_code: str = "routing_error"):
        super().__init__(message)
        self.error_code = error_code
