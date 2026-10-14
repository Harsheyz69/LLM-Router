"""
Request-scoped middleware for request IDs and timing.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger("middleware")

# Context variable holding the current request ID — accessible anywhere in the call stack
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_ctx.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request and measure timing."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = req_id
            logger.info(
                "method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                req_id,
            )
            return response
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "method=%s path=%s error duration_ms=%.1f request_id=%s",
                request.method,
                request.url.path,
                elapsed_ms,
                req_id,
            )
            raise
        finally:
            request_id_ctx.reset(token)
