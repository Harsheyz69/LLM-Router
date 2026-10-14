"""
Chat API endpoint.

Handles both streaming and non-streaming chat requests.
Orchestrates: validation → routing → provider call → response.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.middleware import get_request_id
from app.providers.service import ProviderError, ProviderService
from app.router.policy import RoutingDecision, RoutingError, RoutingPolicy
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    MessageRole,
    RoutingInfo,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamMetaEvent,
    StreamRoutingEvent,
    UsageInfo,
)

logger = get_logger("chat")

router = APIRouter(prefix="/api/v1", tags=["chat"])

# Service singletons (initialized on first use)
_routing_policy: RoutingPolicy | None = None
_provider_service: ProviderService | None = None


def _get_routing_policy() -> RoutingPolicy:
    global _routing_policy
    if _routing_policy is None:
        _routing_policy = RoutingPolicy()
    return _routing_policy


def _get_provider_service() -> ProviderService:
    global _provider_service
    if _provider_service is None:
        _provider_service = ProviderService()
    return _provider_service


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse | StreamingResponse:
    """
    Process a chat request.

    - Validates the prompt against configured limits
    - Routes to a suitable model via the routing policy
    - Calls the selected provider
    - Returns the response (streaming or non-streaming)
    """
    settings = get_settings()
    req_id = get_request_id() or str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())

    # Validate prompt length against configured limit
    if len(request.message) > settings.max_prompt_length:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                error_code="prompt_too_long",
                message=f"Prompt exceeds maximum length of {settings.max_prompt_length} characters.",
                request_id=req_id,
            ).model_dump(),
        )

    # Route the request
    try:
        routing_decision = await _get_routing_policy().route(
            message=request.message,
            preferences=request.preferences,
        )
    except RoutingError as exc:
        logger.warning("Routing failed: %s request_id=%s", str(exc), req_id)
        raise HTTPException(
            status_code=503,
            detail=ErrorDetail(
                error_code=exc.error_code,
                message=str(exc),
                request_id=req_id,
            ).model_dump(),
        )

    # Build messages for the provider
    messages = [{"role": "user", "content": request.message}]

    # Handle streaming
    if request.stream:
        return StreamingResponse(
            _stream_response(
                routing_decision=routing_decision,
                messages=messages,
                req_id=req_id,
                conversation_id=conversation_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-ID": req_id,
            },
        )

    # Non-streaming response
    try:
        provider_response = await _get_provider_service().complete(
            model=routing_decision.selected_model,
            messages=messages,
        )
    except ProviderError as exc:
        # Try fallback to another candidate
        logger.warning(
            "Provider failed for %s, attempting fallback: %s",
            routing_decision.selected_model.model_id,
            str(exc),
        )
        fallback_model = _get_routing_policy().get_fallback_model(
            routing_decision.filter_result.candidates,
            exclude_model_id=routing_decision.selected_model.model_id,
        )
        if fallback_model:
            try:
                provider_response = await _get_provider_service().complete(
                    model=fallback_model,
                    messages=messages,
                )
                # Update routing info to reflect fallback
                routing_decision.selected_model = fallback_model
                routing_decision.fallback_used = True
                routing_decision.decision_result.reason = (
                    f"Fallback to {fallback_model.display_name} "
                    f"after {exc.model_id} failed"
                )
            except ProviderError as fallback_exc:
                raise HTTPException(
                    status_code=502,
                    detail=ErrorDetail(
                        error_code="provider_error",
                        message="All attempted providers failed. Please try again later.",
                        request_id=req_id,
                    ).model_dump(),
                ) from fallback_exc
        else:
            raise HTTPException(
                status_code=502,
                detail=ErrorDetail(
                    error_code="provider_error",
                    message="The model provider is currently unavailable. Please try again later.",
                    request_id=req_id,
                ).model_dump(),
            ) from exc

    routing_info = routing_decision.to_routing_info()
    if routing_decision.fallback_used:
        routing_info.fallback_used = True

    return ChatResponse(
        request_id=req_id,
        conversation_id=conversation_id,
        message=provider_response.content,
        role=MessageRole.assistant,
        routing=routing_info,
        usage=provider_response.usage,
        latency_ms=round(provider_response.latency_ms, 1),
    )


async def _stream_response(
    routing_decision: RoutingDecision,
    messages: list[dict[str, str]],
    req_id: str,
    conversation_id: str,
) -> AsyncIterator[str]:
    """Generate SSE events for a streaming chat response."""

    # Event 1: Meta
    meta = StreamMetaEvent(request_id=req_id, conversation_id=conversation_id)
    yield _sse_event("meta", meta.model_dump())

    # Event 2: Routing info
    routing_info = routing_decision.to_routing_info()
    routing_event = StreamRoutingEvent(routing=routing_info)
    yield _sse_event("routing", routing_event.model_dump())

    # Event 3+: Token chunks
    try:
        async for chunk in _get_provider_service().stream_complete(
            model=routing_decision.selected_model,
            messages=messages,
        ):
            yield _sse_event("token", {"text": chunk})

        # Event N: Done
        done = StreamDoneEvent(latency_ms=None)
        yield _sse_event("done", done.model_dump())

    except ProviderError as exc:
        error = StreamErrorEvent(
            error_code="provider_error",
            message="The model encountered an error while generating. Please try again.",
        )
        yield _sse_event("error", error.model_dump())
        logger.warning(
            "Stream error for %s: %s request_id=%s",
            routing_decision.selected_model.model_id,
            str(exc),
            req_id,
        )
    except Exception as exc:
        error = StreamErrorEvent(
            error_code="internal_error",
            message="An unexpected error occurred during streaming.",
        )
        yield _sse_event("error", error.model_dump())
        logger.exception("Unexpected stream error request_id=%s", req_id)


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
