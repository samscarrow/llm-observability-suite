"""Database logging helpers for applications using this suite."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .core import get_logger


@dataclass
class GenerationDBLogger:
    """Lightweight event logger used during retries and fallbacks."""

    enabled: bool = False
    logger_name: str = "observability.db"
    _logger: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = get_logger(self.logger_name)

    def log_event(
        self,
        *,
        kind: str,
        provider_name: str,
        provider_type: str,
        provider_endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        model_key: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return

        payload = {
            "event": "generation_db_log",
            "kind": kind,
            "provider_name": provider_name,
            "provider_type": provider_type,
            "provider_endpoint": provider_endpoint,
        }
        if model_key:
            payload["model_key"] = model_key
        if data:
            payload["data"] = data

        try:
            self._logger.info(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            self._logger.info(str(payload))


class DBLogger:
    """Best-effort relational logger for generation metadata."""

    def __init__(self, db_uri: str):
        import sqlalchemy

        self._engine = sqlalchemy.create_engine(db_uri)

    def log_event(self, table_name: str, event_data: Dict[str, Any]) -> None:
        from sqlalchemy import text

        columns = ", ".join(event_data.keys())
        placeholders = ", ".join(f":{key}" for key in event_data.keys())
        stmt = text(f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})")

        with self._engine.begin() as conn:
            conn.execute(stmt, event_data)
