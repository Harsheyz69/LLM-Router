"""
FastAPI application entry point.

Configures middleware, CORS, routes, and error handlers.
The backend remains runnable even without all external services configured.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestIdMiddleware
from app.schemas.api import ErrorDetail

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown."""
    settings = get_settings()

    # Configure logging
    setup_logging(
        level=settings.app_log_level,
        is_development=settings.is_development,
    )

    logger.info(
        "Starting Adaptive Multi-LLM Router (env=%s, debug=%s)",
        settings.app_env,
        settings.app_debug,
    )

    # Log provider availability (without revealing keys)
    for provider in ["openai", "anthropic", "google"]:
        configured = settings.has_provider_key(provider)
        logger.info("Provider %s: %s", provider, "configured" if configured else "not configured")

    logger.info("Ollama base URL: %s", settings.ollama_base_url)

    yield

    logger.info("Shutting down Adaptive Multi-LLM Router")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Adaptive Multi-LLM Router",
        description=(
            "Intelligent routing of user prompts to suitable LLMs based on "
            "capabilities, quality, cost, latency, and availability."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    # --- Middleware ---
    # Order matters: first added = outermost wrapper

    # Request ID and timing
    app.add_middleware(RequestIdMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # --- Routes ---
    app.include_router(health_router)
    app.include_router(chat_router)

    # --- Error handlers ---
    @app.exception_handler(422)
    async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Return consistent error format for validation errors."""
        from app.core.middleware import get_request_id

        return JSONResponse(
            status_code=422,
            content=ErrorDetail(
                error_code="validation_error",
                message="Invalid request. Please check your input.",
                request_id=get_request_id(),
            ).model_dump(),
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Never expose stack traces or internal details."""
        from app.core.middleware import get_request_id

        logger.exception("Unhandled error: %s", str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorDetail(
                error_code="internal_error",
                message="An unexpected error occurred. Please try again.",
                request_id=get_request_id(),
            ).model_dump(),
        )

    return app


# Application instance
app = create_app()
