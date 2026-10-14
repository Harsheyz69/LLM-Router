"""
Tests for the query analyzer.
"""

from __future__ import annotations

from app.router.analyzer import QueryFeatures, analyze_query
from app.schemas.api import TaskCategory


class TestQueryAnalyzer:
    """Test query classification and feature extraction."""

    def test_coding_query(self):
        features = analyze_query("Write a Python function to sort a list")
        assert features.task_category == TaskCategory.coding

    def test_math_query(self):
        features = analyze_query("Calculate the derivative of x^2 + 3x")
        assert features.task_category == TaskCategory.math

    def test_creative_query(self):
        features = analyze_query("Write a story about a dragon")
        assert features.task_category == TaskCategory.creative

    def test_summarization_query(self):
        features = analyze_query("Summarize the following article")
        assert features.task_category == TaskCategory.summarization

    def test_translation_query(self):
        features = analyze_query("Translate this to Spanish")
        assert features.task_category == TaskCategory.translation

    def test_analysis_query(self):
        features = analyze_query("Analyze the pros and cons of remote work")
        assert features.task_category == TaskCategory.analysis

    def test_general_query(self):
        features = analyze_query("What is the capital of France?")
        assert features.task_category == TaskCategory.general

    def test_token_estimation(self):
        short = analyze_query("Hi")
        long_msg = "x " * 1000
        long_features = analyze_query(long_msg)
        assert short.estimated_input_tokens < long_features.estimated_input_tokens

    def test_output_token_estimation(self):
        coding = analyze_query("Write a Python function")
        summary = analyze_query("Summarize this text")
        # Coding should estimate more output tokens than summarization
        # (for similar-length prompts)
        assert coding.estimated_output_tokens >= summary.estimated_output_tokens

    def test_complexity_estimation(self):
        short = analyze_query("Hi")
        assert short.complexity == "low"

        medium = analyze_query("Explain how binary search works in detail with examples")
        assert medium.complexity in ("low", "medium")

    def test_features_have_positive_token_estimates(self):
        features = analyze_query("Any prompt")
        assert features.estimated_input_tokens > 0
        assert features.estimated_output_tokens > 0
        assert features.estimated_total_tokens > 0
