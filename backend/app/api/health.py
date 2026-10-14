"""
Health check endpoint.

Returns liveness/readiness status without exposing secrets or internal config.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        Application status, version, environment, and provider availability.
    """
    settings = get_settings()

    # Report which providers have keys configured (not whether they're healthy)
    providers = {
        "openai": settings.has_provider_key("openai"),
        "anthropic": settings.has_provider_key("anthropic"),
        "google": settings.has_provider_key("google"),
        "ollama": bool(settings.ollama_base_url),
    }

    return HealthResponse(
        status="ok",
        version="0.1.0",
        environment=settings.app_env,
        providers=providers,
        timestamp=datetime.now(timezone.utc),
    )
