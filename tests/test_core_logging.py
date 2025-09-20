import json
from typing import Any

import pytest

from llm_observability import (
    ErrorCodes,
    get_logger,
    init_logging_from_env,
    log_exception,
    JsonLogFormatter,
)


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch: pytest.MonkeyPatch):
    # Ensure a clean logging config for each test
    for var, val in {
        "LOG_FORMAT": "json",
        "LOG_DEST": "stdout",
        "LOG_LEVEL": "INFO",
        "SERVICE_NAME": "test-service",
        "TRACE_ID": "tid-123",
        "CORRELATION_ID": "cid-456",
    }.items():
        monkeypatch.setenv(var, val)

    init_logging_from_env(force=True)
    yield


def formatted_last_record(caplog) -> dict[str, Any]:
    assert caplog.records, "no log records captured"
    rec = caplog.records[-1]
    formatted = JsonLogFormatter().format(rec)
    return json.loads(formatted)


def test_structured_info_log_with_redaction(caplog):
    logger = get_logger("unit.core", component="worker", endpoint="/api")
    logger.info("hello", extra={"custom": "x", "api_key": "secret"})
    payload = formatted_last_record(caplog)

    assert payload["level"] == "INFO"
    assert payload["name"] == "unit.core"
    assert payload["message"] == "hello"
    assert payload["service"] == "test-service"
    assert payload["trace_id"] == "tid-123"
    assert payload["correlation_id"] == "cid-456"
    assert payload["component"] == "worker"
    assert payload["endpoint"] == "/api"
    assert payload["custom"] == "x"
    # api_key should be redacted by the formatter
    assert payload["api_key"] == "[REDACTED]"


def test_log_exception_includes_code_and_exc(caplog):
    logger = get_logger("unit.core")
    try:
        raise ValueError("BOOM")
    except Exception as e:  # noqa: PERF203
        log_exception(logger, code=ErrorCodes.GEN_PARSE_ERROR, component="parser", exc=e, step="phase1")

    payload = formatted_last_record(caplog)
    assert payload["level"] == "ERROR"
    assert payload["event"] == "error"
    assert payload["error_code"] == ErrorCodes.GEN_PARSE_ERROR
    assert payload["component"] == "parser"
    assert payload["error"].startswith("BOOM") or payload["message"].startswith("BOOM")
    # exc_info field is optional but should exist for exceptions
    assert "exc_info" in payload
