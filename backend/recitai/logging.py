"""Structured logging (spec §16 task 6).

Human-readable in development, JSON in production, selected by `LOG_FORMAT`. Every log
line emitted while handling a request carries that request's id, so a failed ingest or a
slow generation can be traced through the pipeline without correlating timestamps by eye.
"""

import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: Set per request and read by every log call beneath it, including ones several layers
#: down that know nothing about HTTP.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "X-Request-ID"


def _add_request_id(
    _logger: object, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    rid = request_id.get()
    if rid is not None:
        event["request_id"] = rid
    return event


def configure(log_format: str = "console", level: str = "INFO") -> None:
    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if log_format == "json":
        processors += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign or adopt a request id and echo it back on the response.

    An inbound `X-Request-ID` is honoured so a trace survives a proxy in front of the app.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        # One structured line per request, carrying the id every log beneath it also
        # carried — which is what makes the id worth assigning.
        structlog.get_logger(__name__).info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=int((time.perf_counter() - started) * 1000),
            request_id=rid,
        )
        return response
