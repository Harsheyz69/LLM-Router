"""
Query analyzer.

Derives task features and constraints from the user's prompt
to inform routing decisions. Does not make routing decisions itself.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.schemas.api import TaskCategory

logger = get_logger("analyzer")

# Simple keyword-based classification — sufficient for MVP.
# Future: use a lightweight classifier or LLM-based analysis.
_CATEGORY_PATTERNS: list[tuple[TaskCategory, list[str]]] = [
    (TaskCategory.coding, [
        r"\bcode\b", r"\bpython\b", r"\bjavascript\b", r"\btypescript\b",
        r"\bfunction\b", r"\bclass\b", r"\bapi\b", r"\bdebug\b",
        r"\bprogram\b", r"\balgorithm\b", r"\bsyntax\b", r"\bgit\b",
        r"\bsql\b", r"\bhtml\b", r"\bcss\b", r"\brust\b", r"\bjava\b",
        r"\bcompile\b", r"\bregex\b", r"\bscript\b", r"\bbug\b",
        r"\bimport\b", r"\bmodule\b", r"\bpackage\b",
    ]),
    (TaskCategory.math, [
        r"\bcalculat\w*\b", r"\bequation\b", r"\bmath\b", r"\bsolve\b",
        r"\bderivative\b", r"\bintegral\b", r"\bproof\b", r"\bstatistic\b",
        r"\bprobability\b", r"\balgebra\b", r"\bgeometry\b",
    ]),
    (TaskCategory.creative, [
        r"\bwrite\s+a\s+(story|poem|song|essay)\b", r"\bcreative\b",
        r"\bimagin\w*\b", r"\bfiction\b", r"\bpoetry\b", r"\bnarrative\b",
        r"\bbrainstorm\b",
    ]),
    (TaskCategory.analysis, [
        r"\banalyz\w*\b", r"\bcompare\b", r"\bevaluat\w*\b",
        r"\bexplain\s+the\s+difference\b", r"\bpros\s+and\s+cons\b",
        r"\bcritique\b", r"\breview\b", r"\bassess\b",
    ]),
    (TaskCategory.summarization, [
        r"\bsummariz\w*\b", r"\btl;?dr\b", r"\bbrief\b",
        r"\bcondense\b", r"\boverview\b", r"\bsynopsis\b",
    ]),
    (TaskCategory.translation, [
        r"\btranslat\w*\b", r"\bconvert\s+to\s+\w+\b",
        r"\bin\s+(spanish|french|german|chinese|japanese|korean|hindi)\b",
    ]),
]


class QueryFeatures:
    """Extracted features from the user's query."""

    def __init__(
        self,
        task_category: TaskCategory,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        requires_tools: bool = False,
        requires_vision: bool = False,
        complexity: str = "medium",  # low, medium, high
    ):
        self.task_category = task_category
        self.estimated_input_tokens = estimated_input_tokens
        self.estimated_output_tokens = estimated_output_tokens
        self.requires_tools = requires_tools
        self.requires_vision = requires_vision
        self.complexity = complexity

    @property
    def estimated_total_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (~4 chars per token for English text)."""
    return max(1, len(text) // 4)


def _estimate_output_tokens(category: TaskCategory, input_tokens: int) -> int:
    """Estimate expected output length based on task category."""
    multipliers = {
        TaskCategory.coding: 3.0,
        TaskCategory.creative: 3.0,
        TaskCategory.analysis: 2.5,
        TaskCategory.math: 2.0,
        TaskCategory.summarization: 0.5,
        TaskCategory.translation: 1.2,
        TaskCategory.conversation: 1.5,
        TaskCategory.general: 2.0,
    }
    multiplier = multipliers.get(category, 2.0)
    # Clamp to reasonable range
    return max(50, min(int(input_tokens * multiplier), 4096))


def _classify_task(message: str) -> TaskCategory:
    """Classify the task based on keyword patterns."""
    message_lower = message.lower()
    scores: dict[TaskCategory, int] = {}

    for category, patterns in _CATEGORY_PATTERNS:
        score = sum(1 for p in patterns if re.search(p, message_lower))
        if score > 0:
            scores[category] = score

    if not scores:
        return TaskCategory.general

    return max(scores, key=scores.get)  # type: ignore[arg-type]


def _estimate_complexity(message: str, category: TaskCategory) -> str:
    """Estimate query complexity."""
    length = len(message)
    if length < 50:
        return "low"
    elif length < 500 or category in (TaskCategory.conversation, TaskCategory.general):
        return "medium"
    else:
        return "high"


def analyze_query(message: str) -> QueryFeatures:
    """
    Analyze a user query and extract features for routing.

    This is a lightweight heuristic — not a proven classifier.
    """
    category = _classify_task(message)
    input_tokens = _estimate_tokens(message)
    output_tokens = _estimate_output_tokens(category, input_tokens)
    complexity = _estimate_complexity(message, category)

    features = QueryFeatures(
        task_category=category,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        requires_tools=False,
        requires_vision=False,
        complexity=complexity,
    )

    logger.debug(
        "Query analysis: category=%s complexity=%s est_tokens=%d",
        category.value,
        complexity,
        features.estimated_total_tokens,
    )

    return features
