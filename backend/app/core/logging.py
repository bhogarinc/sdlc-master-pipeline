"""Structured logging with correlation IDs."""

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Dict

import structlog
from structlog.processors import JSONRenderer, TimeStamper
from structlog.stdlib import add_log_level

from app.core.config import settings

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    cid = correlation_id.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    correlation_id.set(cid)


class CorrelationIdProcessor:
    def __call__(self, logger: Any, method_name: str, event_dict: Dict) -> Dict:
        event_dict["correlation_id"] = get_correlation_id()
        return event_dict


def configure_logging() -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_log_level,
        TimeStamper(fmt="iso"),
        CorrelationIdProcessor(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    renderer = JSONRenderer() if settings.LOG_FORMAT == "json" else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.LOG_LEVEL)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
