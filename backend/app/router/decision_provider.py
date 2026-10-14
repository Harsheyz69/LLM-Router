"""
Decision provider interface.

Defines the abstract contract for decision-layer components.
Implementations include RuleBasedDecisionProvider (baseline)
and JevDecisionProvider (experimental, pending verification).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.registry.schemas import ModelEntry
from app.router.analyzer import QueryFeatures
from app.schemas.api import ChatPreferences


@dataclass
class ModelScore:
    """Score and rationale for a single model candidate."""
    model_id: str
    score: float  # Higher is better
    reason: str = ""
    quality_component: float = 0.0
    cost_component: float = 0.0
    latency_component: float = 0.0
    preference_component: float = 0.0


@dataclass
class DecisionResult:
    """Output of the decision layer."""
    scores: list[ModelScore] = field(default_factory=list)
    selected_model_id: Optional[str] = None
    confidence: Optional[float] = None  # 0.0-1.0, None if not meaningful
    reason: str = ""
    decision_provider: str = ""  # e.g. "rule_based", "jev"

    @property
    def is_valid(self) -> bool:
        """Check if the decision result is usable."""
        return (
            self.selected_model_id is not None
            and len(self.scores) > 0
        )


class DecisionProvider(ABC):
    """
    Abstract decision-layer interface.

    Implementations provide structured suitability signals for
    candidate models. The routing policy makes the final selection.
    """

    @abstractmethod
    async def decide(
        self,
        features: QueryFeatures,
        candidates: list[ModelEntry],
        preferences: ChatPreferences,
    ) -> DecisionResult:
        """
        Evaluate candidates and return scored recommendations.

        Args:
            features: Extracted query features.
            candidates: Models that passed hard-constraint filtering.
            preferences: User's routing preferences.

        Returns:
            DecisionResult with scored candidates and a recommendation.
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name of this decision provider."""
        ...
