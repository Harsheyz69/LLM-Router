"""
Provider service — LiteLLM integration.

Isolates model-specific provider details from the router.
Handles timeouts, retries, errors, and response normalization.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.registry.schemas import HealthStatus, ModelEntry
from app.schemas.api import UsageInfo

logger = get_logger("provider")


class ProviderError(Exception):
    """Raised when a provider call fails."""

    def __init__(
        self,
        message: str,
        provider: str = "",
        model_id: str = "",
        is_retryable: bool = False,
        is_rate_limit: bool = False,
    ):
        super().__init__(message)
        self.provider = provider
        self.model_id = model_id
        self.is_retryable = is_retryable
        self.is_rate_limit = is_rate_limit


class ProviderResponse:
    """Normalized response from any provider."""

    def __init__(
        self,
        content: str,
        model_id: str,
        provider: str,
        usage: Optional[UsageInfo] = None,
        latency_ms: float = 0.0,
        raw_model_name: Optional[str] = None,
    ):
        self.content = content
        self.model_id = model_id
        self.provider = provider
        self.usage = usage
        self.latency_ms = latency_ms
        self.raw_model_name = raw_model_name


class ProviderService:
    """
    Service that calls LLM providers through LiteLLM.

    Handles:
    - Configurable timeouts
    - Bounded retries (max 2 for retryable errors)
    - Response normalization
    - Error classification (rate limit, timeout, auth, etc.)
    """

    MAX_RETRIES = 2

    def __init__(self) -> None:
        self._settings = get_settings()

    async def complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, str]],
        stream: bool = False,
        timeout: Optional[float] = None,
    ) -> ProviderResponse:
        """
        Call a model through LiteLLM and return a normalized response.

        Args:
            model: The model entry from the registry.
            messages: Chat messages in OpenAI format.
            stream: Whether to stream (not used here — see stream_complete).
            timeout: Request timeout in seconds.

        Returns:
            Normalized ProviderResponse.

        Raises:
            ProviderError on failure after retries.
        """
        import litellm

        timeout = timeout or self._settings.request_timeout_seconds

        litellm_model = model.effective_litellm_model
        api_key = self._get_api_key(model.provider)
        api_base = self._get_api_base(model.provider)

        # Suppress LiteLLM's own verbose logging
        litellm.suppress_debug_info = True

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "timeout": timeout,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        last_error: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            start = time.perf_counter()
            try:
                response = await litellm.acompletion(**kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000

                # Extract content
                content = response.choices[0].message.content or ""

                # Extract usage
                usage = None
                if hasattr(response, "usage") and response.usage:
                    usage = UsageInfo(
                        prompt_tokens=getattr(response.usage, "prompt_tokens", None),
                        completion_tokens=getattr(response.usage, "completion_tokens", None),
                        total_tokens=getattr(response.usage, "total_tokens", None),
                    )

                logger.info(
                    "Provider call success: model=%s provider=%s latency_ms=%.1f tokens=%s",
                    model.model_id,
                    model.provider,
                    elapsed_ms,
                    usage.total_tokens if usage else "unknown",
                )

                return ProviderResponse(
                    content=content,
                    model_id=model.model_id,
                    provider=model.provider,
                    usage=usage,
                    latency_ms=elapsed_ms,
                    raw_model_name=getattr(response, "model", None),
                )

            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start) * 1000
                last_error = exc
                error_info = _classify_error(exc, model)

                logger.warning(
                    "Provider call failed (attempt %d/%d): model=%s error=%s latency_ms=%.1f",
                    attempt,
                    self.MAX_RETRIES,
                    model.model_id,
                    str(exc)[:200],
                    elapsed_ms,
                )

                if not error_info.is_retryable or attempt >= self.MAX_RETRIES:
                    raise ProviderError(
                        message=_safe_error_message(exc),
                        provider=model.provider,
                        model_id=model.model_id,
                        is_retryable=error_info.is_retryable,
                        is_rate_limit=error_info.is_rate_limit,
                    ) from exc

        # Should not reach here, but just in case
        raise ProviderError(
            message="Provider call failed after all retries",
            provider=model.provider,
            model_id=model.model_id,
        )

    async def stream_complete(
        self,
        model: ModelEntry,
        messages: list[dict[str, str]],
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a completion from a model through LiteLLM.

        Yields text chunks as they arrive.
        """
        import litellm

        timeout = timeout or self._settings.request_timeout_seconds

        litellm_model = model.effective_litellm_model
        api_key = self._get_api_key(model.provider)
        api_base = self._get_api_base(model.provider)

        litellm.suppress_debug_info = True

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "timeout": timeout,
            "stream": True,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        try:
            response = await litellm.acompletion(**kwargs)
            async for chunk in response:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        yield delta.content
        except Exception as exc:
            raise ProviderError(
                message=_safe_error_message(exc),
                provider=model.provider,
                model_id=model.model_id,
            ) from exc

    def _get_api_key(self, provider: str) -> str | None:
        """Get the API key for a provider. Returns None if not configured."""
        key_map = {
            "openai": self._settings.openai_api_key,
            "anthropic": self._settings.anthropic_api_key,
            "google": self._settings.google_api_key,
        }
        return key_map.get(provider)

    def _get_api_base(self, provider: str) -> str | None:
        """Get the base URL for providers that need it."""
        if provider == "ollama":
            return self._settings.ollama_base_url
        return None


class _ErrorInfo:
    """Classified error information."""

    def __init__(self, is_retryable: bool = False, is_rate_limit: bool = False):
        self.is_retryable = is_retryable
        self.is_rate_limit = is_rate_limit


def _classify_error(exc: Exception, model: ModelEntry) -> _ErrorInfo:
    """Classify a provider error for retry/fallback decisions."""
    error_str = str(exc).lower()

    # Rate limits
    if "rate_limit" in error_str or "429" in error_str or "too many requests" in error_str:
        return _ErrorInfo(is_retryable=True, is_rate_limit=True)

    # Timeouts
    if "timeout" in error_str or "timed out" in error_str:
        return _ErrorInfo(is_retryable=True)

    # Server errors (5xx)
    if any(f"{code}" in error_str for code in range(500, 600)):
        return _ErrorInfo(is_retryable=True)

    # Connection errors
    if "connection" in error_str or "connect" in error_str:
        return _ErrorInfo(is_retryable=True)

    # Auth errors — not retryable
    if "auth" in error_str or "401" in error_str or "403" in error_str:
        return _ErrorInfo(is_retryable=False)

    # Default: not retryable
    return _ErrorInfo(is_retryable=False)


def _safe_error_message(exc: Exception) -> str:
    """Create a user-safe error message without secrets or stack traces."""
    error_str = str(exc)

    # Remove anything that looks like a key or token
    from app.core.logging import redact_secrets
    safe = redact_secrets(error_str)

    # Truncate long messages
    if len(safe) > 200:
        safe = safe[:200] + "..."

    return safe
