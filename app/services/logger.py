"""
logger.py
Centralized logging helper for the DND + AI server.

Features:
- Application-wide logger initialization
- Debug vs operations logging split
- JSON-formatted logs for intelligence + service layers
- Rotating file handlers
- Simple import pattern: from logger import get_logger
"""

import json
import logging
import logging.handlers
import os
from datetime import datetime
from typing import Any, Dict

# ---------------------------------------------------------------------------
# JSON Formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """
    Emit logs as structured JSON objects.
    Useful for AI pipeline debugging, telemetry, and ingestion into log tools.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Handler Builder
# ---------------------------------------------------------------------------

def _build_handler(
    *,
    filename: str,
    level: int,
    json_format: bool,
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Handler:
    """
    Build a rotating file handler with either text or JSON formatting.
    """

    handler = logging.handlers.RotatingFileHandler(
        filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )

    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    handler.setLevel(level)
    return handler


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_logging(
    *,
    log_dir: str = "logs",
    debug_enabled: bool = False,
) -> None:
    """
    Initialize the global logging configuration.

    debug_enabled=True → verbose developer logs
    debug_enabled=False → production operations logs only
    """

    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # Debug logs (text)
    debug_handler = _build_handler(
        filename=os.path.join(log_dir, "debug.log"),
        level=logging.DEBUG if debug_enabled else logging.INFO,
        json_format=False,
    )

    # Operations logs (JSON)
    ops_handler = _build_handler(
        filename=os.path.join(log_dir, "operations.jsonl"),
        level=logging.INFO,
        json_format=True,
    )

    root.addHandler(debug_handler)
    root.addHandler(ops_handler)

    # Console output
    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    console.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
    root.addHandler(console)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """
    Retrieve a logger for any module.
    Usage:
        log = get_logger(__name__)
        log.info("Something happened")
    """
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Optional: Standalone Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_logging(debug_enabled=True)
    log = get_logger("logger_test")
    log.info("Logger initialized for standalone test.")
