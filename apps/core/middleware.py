import logging
import time
import uuid

from .logging import request_id_var

logger = logging.getLogger("apps.request")


class RequestLogMiddleware:
    """Gives each request an id, and logs one line per request when it finishes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            logger.info(
                "request",
                extra={
                    "ctx": {
                        "method": request.method,
                        "path": request.path,
                        "status": response.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            return response
        finally:
            request_id_var.reset(token)
