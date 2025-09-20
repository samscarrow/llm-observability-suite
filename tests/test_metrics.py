import json
from typing import Any

import pytest

from llm_observability import (
    inc_metric,
    init_logging_from_env,
    metric_event,
    observe_metric,
    timing,
    JsonLogFormatter,
)


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch: pytest.MonkeyPatch):
    for var, val in {
        "LOG_FORMAT": "json",
        "LOG_DEST": "stdout",
        "LOG_LEVEL": "INFO",
        "SERVICE_NAME": "test-service",
    }.items():
        monkeypatch.setenv(var, val)
    init_logging_from_env(force=True)
    yield


def formatted_last_record(caplog) -> dict[str, Any]:
    assert caplog.records, "no log records captured"
    rec = caplog.records[-1]
    formatted = JsonLogFormatter().format(rec)
    return json.loads(formatted)


def parse_inner_message(payload: dict[str, Any]) -> dict[str, Any]:
    # metric_event and friends log a JSON string as the message
    return json.loads(payload["message"]) if isinstance(payload.get("message"), str) else {}


def test_metric_event_logs_payload(caplog):
    metric_event("my.counter", value=2, type="counter", unit="n", tag="A")
    outer = formatted_last_record(caplog)
    inner = parse_inner_message(outer)

    assert outer["name"] == "metrics"
    assert inner["event"] == "metric"
    assert inner["metric"] == "my.counter"
    assert inner["value"] == 2
    assert inner["type"] == "counter"
    assert inner["unit"] == "n"
    assert inner["tag"] == "A"


def test_inc_metric_sets_counter_type(caplog):
    inc_metric("requests.total", 3, route="/v1")
    inner = parse_inner_message(formatted_last_record(caplog))
    assert inner["metric"] == "requests.total"
    assert inner["value"] == 3
    assert inner["type"] == "counter"
    assert inner["route"] == "/v1"


def test_observe_metric_timer_type(caplog):
    observe_metric("latency.ms", 123.4, unit="ms", component="worker")
    inner = parse_inner_message(formatted_last_record(caplog))
    assert inner["metric"] == "latency.ms"
    assert inner["value"] == 123.4
    assert inner["unit"] == "ms"
    assert inner["type"] == "timer"
    assert inner["component"] == "worker"


def test_timing_context_manager_emits_ms(caplog):
    with timing("block.time_ms"):
        for _ in range(10000):
            pass
    inner = parse_inner_message(formatted_last_record(caplog))
    assert inner["metric"] == "block.time_ms"
    assert inner["unit"] == "ms"
    assert inner["type"] == "timer"
    assert inner["value"] >= 0
