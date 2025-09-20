"""Core logging and metrics helpers for llm-observability-suite."""

from __future__ import annotations

import json
import logging
import os
import sys
from enum import Enum
from contextlib import contextmanager
import time
from typing import Any, Dict, Optional

__all__ = [
    "ErrorCodes",
    "JsonLogFormatter",
    "init_logging_from_env",
    "get_logger",
    "log_exception",
    "metric_event",
    "observe_metric",
    "inc_metric",
    "timing",
]

_CONFIGURED = False
_CURRENT_CONFIG: Optional[tuple[str, str, str, str]] = None
_DEFAULT_SERVICE = os.getenv("SERVICE_NAME", "llm-app") or "llm-app"
_METRIC_LOGGER_NAME = "metrics"


class ErrorCodes(str, Enum):
    """Stable error codes consumed by dashboards and alerting."""

    AI_LB_UNAVAILABLE = "AI_LB_UNAVAILABLE"
    GEN_TIMEOUT = "GEN_TIMEOUT"
    GEN_PARSE_ERROR = "GEN_PARSE_ERROR"
    CONFIG_INVALID = "CONFIG_INVALID"
    GEN_DB_ERROR = "GEN_DB_ERROR"


class JsonLogFormatter(logging.Formatter):
    """Minimal JSON log formatter with structured context support."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }

        base_keys = (
            "correlation_id",
            "trace_id",
            "message_id",
            "job_id",
            "step",
            "service",
            "endpoint",
            "model",
            "provider",
            "elapsed_ms",
            "ok",
            "len",
            "event",
            "attempt",
            "error",
            "error_code",
        )
        redact = {"api_key", "authorization", "password", "db_password", "oracle_password"}

        for key in base_keys:
            if hasattr(record, key):
                val = getattr(record, key)
                payload[key] = "[REDACTED]" if key in redact else val

        std_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "asctime",
        }

        for key, value in record.__dict__.items():
            if key in payload or key in std_attrs or key.startswith("_"):
                continue
            if callable(value):
                continue
            try:
                payload[key] = "[REDACTED]" if key in redact else value
                json.dumps(payload[key])
            except Exception:
                payload[key] = str(value)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class _Adapter(logging.LoggerAdapter):
    """Inject default service context into log records."""

    def process(self, msg: str, kwargs: Dict[str, Any]):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("service", _DEFAULT_SERVICE)
        extra.setdefault("trace_id", os.getenv("TRACE_ID", ""))
        extra.setdefault("correlation_id", os.getenv("CORRELATION_ID", ""))
        return msg, kwargs


def init_logging_from_env(force: bool = False) -> None:
    """Configure the root logger based on environment variables."""

    global _CONFIGURED
    fmt = (os.getenv("LOG_FORMAT", "json") or "json").strip().lower()
    dest = (os.getenv("LOG_DEST", "stderr") or "stderr").strip().lower()
    level_name = (os.getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper()
    file_path = os.getenv("LOG_FILE_PATH", "app.log") or "app.log"

    level = getattr(logging, level_name, logging.INFO)

    config_key = (fmt, dest, level_name, file_path)
    if not force and _CONFIGURED and config_key == _CURRENT_CONFIG:
        return

    if dest == "stdout":
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
    elif dest == "stderr":
        handler = logging.StreamHandler(sys.stderr)
    elif dest == "file":
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        handler = logging.FileHandler(file_path)
    else:
        handler = logging.StreamHandler(sys.stderr)

    formatter: logging.Formatter
    if fmt == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)

    _CONFIGURED = True
    globals()["_CURRENT_CONFIG"] = config_key


def get_logger(name: str, *, service: Optional[str] = None, **context: Any) -> logging.LoggerAdapter:
    """Return a logger adapter with default structured context."""

    init_logging_from_env()
    base = logging.getLogger(name)
    adapter = _Adapter(base, {})
    if service:
        adapter.extra["service"] = service
    if context:
        adapter.extra.update(context)
    return adapter


def log_exception(
    logger: logging.LoggerAdapter,
    *,
    code: ErrorCodes | str,
    component: str,
    exc: Exception,
    **context: Any,
) -> None:
    """Emit a structured error entry."""

    payload = {
        "event": "error",
        "error_code": str(code),
        "component": component,
        "error": str(exc),
    }
    payload.update(context)
    logger.error(str(exc), extra=payload)


def _metric_logger() -> logging.LoggerAdapter:
    return get_logger(_METRIC_LOGGER_NAME)

def metric_event(metric: str, *, value: Any, type: Optional[str] = None, unit: Optional[str] = None, **tags: Any) -> None:
    """Emit a metric-style structured log entry."""

    payload = {
        "event": "metric",
        "metric": metric,
        "value": value,
    }
    if type:
        payload["type"] = type
    if unit:
        payload["unit"] = unit
    payload.update(tags)

    logger = _metric_logger()
    try:
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        logger.info(str(payload))


def observe_metric(metric: str, value: Any, unit: str = "ms", **tags: Any) -> None:
    """Timer-style helper – defaults unit to milliseconds."""

    metric_event(metric, value=value, unit=unit, type=tags.pop("type", "timer"), **tags)


def inc_metric(metric: str, n: int = 1, **tags: Any) -> None:
    """Counter-style helper."""

    metric_event(metric, value=n, type="counter", **tags)


@contextmanager
def timing(metric: str, *, unit: str = "ms", **tags: Any):
    """Context manager to emit a timing metric for a block.

    Example:
        with timing("worker.handle_ms", component="plot_worker"):
            do_work()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if unit == "ms":
            value = elapsed * 1000.0
        elif unit == "s":
            value = elapsed
        else:
            # default to milliseconds if unknown unit
            value = elapsed * 1000.0
            unit_label = "ms"
            observe_metric(metric, value, unit=unit_label, **tags)
            return
        observe_metric(metric, value, unit=unit, **tags)
