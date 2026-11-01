# reference/loader.py
"""
Shared fail-soft loader for app/reference datasets (SPEC-0012 WP-4; PAT-ARCH-006).

load_entries() reads one normalized JSON array once, when services are built. It never raises:
a missing or invalid file logs one WARNING and returns []; an invalid or duplicate entry is
dropped with one WARNING each. Logs carry the dataset, reasons and indexes only.
"""

import json
import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.services.logger import get_logger

T = TypeVar("T", bound=BaseModel)

_default_logger = get_logger(__name__)


def load_entries(
    path: Path | str,
    model: type[T],
    dataset: str,
    logger: logging.Logger = _default_logger,
) -> list[T]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        reason = "missing"
    except (OSError, UnicodeDecodeError):
        reason = "unreadable"
    except ValueError:
        reason = "invalid_json"
    else:
        if isinstance(data, list):
            return _validate_entries(data, model, dataset, logger)
        reason = "not_list"
    logger.warning("reference.unavailable", extra={"dataset": dataset, "reason": reason})
    return []


def _validate_entries(data: list, model: type[T], dataset: str, logger: logging.Logger) -> list[T]:
    entries: list[T] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(data):
        try:
            entry = model.model_validate(raw)
        except ValidationError:
            logger.warning(
                "reference.entry_dropped",
                extra={"dataset": dataset, "index": index, "reason": "invalid"},
            )
            continue
        if entry.id in seen_ids:
            logger.warning(
                "reference.entry_dropped",
                extra={"dataset": dataset, "index": index, "reason": "duplicate_id"},
            )
            continue
        seen_ids.add(entry.id)
        entries.append(entry)
    return entries
