"""
Simple event tracing to a file (JSON lines).
"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


_LOGGER_NAME = "aurora.tracer"
_SINGLETON: Optional["EventTracer"] = None


@dataclass
class EventTracer:
    logfile: str
    level: int = logging.INFO

    def __post_init__(self):
        self._logger = logging.getLogger(_LOGGER_NAME)
        # Ensure idempotent handler setup
        if not self._logger.handlers:
            # Truncate the logfile at startup so each run starts fresh
            try:
                with open(self.logfile, "w", encoding="utf-8"):
                    pass
            except Exception:
                # If truncation fails we proceed; handler will attempt to create the file
                pass
            self._logger.setLevel(self.level)
            # Use append mode after explicit truncation (simplifies idempotency)
            fh = logging.FileHandler(self.logfile, mode="a", encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            fh.setFormatter(fmt)
            self._logger.addHandler(fh)
            self._logger.propagate = False

    def log(self, event: str, **fields: Any) -> None:
        try:
            payload: Dict[str, Any] = {"event": event}
            payload.update(fields)
            self._logger.info(json.dumps(payload, ensure_ascii=False))
        except Exception:
            # Never fail the app due to tracing
            self._logger.info(json.dumps({"event": event, "trace_error": True}))


def get_tracer(logfile: Optional[str] = None) -> EventTracer:
    global _SINGLETON
    if _SINGLETON is not None:
        return _SINGLETON
    # Avoid core import cycles: read env directly
    path = logfile or os.getenv("TRACE_LOG_FILE") or "aurora_trace.log"
    _SINGLETON = EventTracer(path)
    return _SINGLETON

