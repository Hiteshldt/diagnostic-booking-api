"""Structured logging: every log line is one JSON object, tagged with a request id."""

import json
import logging
from contextvars import ContextVar

request_id_var = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """
    Extra fields are passed as `logger.info("msg", extra={"ctx": {...}})` and
    are merged into the top level of the JSON object.
    """

    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        payload.update(getattr(record, "ctx", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
