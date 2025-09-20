import json
import sqlite3
from pathlib import Path

import pytest

from llm_observability import GenerationDBLogger, DBLogger, init_logging_from_env, JsonLogFormatter


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


def parse_inner_message_from_caplog(caplog) -> dict:
    assert caplog.records, "no log records captured"
    rec = caplog.records[-1]
    formatted = JsonLogFormatter().format(rec)
    outer = json.loads(formatted)
    return json.loads(outer["message"]) if isinstance(outer.get("message"), str) else {}


def test_generation_db_logger_emits_when_enabled(caplog):
    g = GenerationDBLogger(enabled=True, logger_name="observability.db")
    g.log_event(
        kind="attempt",
        provider_name="openai",
        provider_type="llm",
        provider_endpoint="/v1/chat",
        data={"attempt": 1},
        model_key="gpt-4o",
    )

    inner = parse_inner_message_from_caplog(caplog)
    assert inner["event"] == "generation_db_log"
    assert inner["kind"] == "attempt"
    assert inner["provider_name"] == "openai"
    assert inner["provider_type"] == "llm"
    assert inner["provider_endpoint"] == "/v1/chat"
    assert inner["model_key"] == "gpt-4o"
    assert inner["data"] == {"attempt": 1}


def test_generation_db_logger_disabled_does_not_log(caplog):
    caplog.clear()
    g = GenerationDBLogger(enabled=False, logger_name="observability.db")
    g.log_event(
        kind="noop",
        provider_name="noop",
        provider_type="noop",
        provider_endpoint="/noop",
    )
    # Ensure nothing was recorded for the specific logger
    assert not any(r.name == "observability.db" for r in caplog.records)


def test_db_logger_inserts_into_sqlite_file(tmp_path: Path):
    db_file = tmp_path / "events.sqlite"
    uri = f"sqlite:///{db_file}"

    # Create table using sqlite3 to avoid importing SQLAlchemy here
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "name TEXT,"
            "value INTEGER,"
            "note TEXT"
            ")"
        )
        conn.commit()

    logger = DBLogger(uri)
    logger.log_event("events", {"name": "row1", "value": 42, "note": "ok"})

    with sqlite3.connect(db_file) as conn:
        cur = conn.execute("SELECT name, value, note FROM events ORDER BY id ASC")
        rows = cur.fetchall()
        assert ("row1", 42, "ok") in rows
