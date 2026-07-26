from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

_SAFE_FIELDS = {
    "alert_type",
    "attempt_count",
    "error_type",
    "incident_id",
    "node",
    "precedent_count",
    "run_id",
    "service",
    "status",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", record.getMessage()),
        }
        for field_name in _SAFE_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_json_logging() -> logging.Logger:
    logger = logging.getLogger("deja")
    if not any(getattr(handler, "_deja_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._deja_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    safe_fields = {
        field_name: value
        for field_name, value in fields.items()
        if field_name in _SAFE_FIELDS and value is not None
    }
    logger.log(level, event, extra={"event": event, **safe_fields})
