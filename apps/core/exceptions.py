"""
One error shape for the whole API:

    {"error": {"code": "conflict", "message": "...", "details": {...}}}

`details` is only present for validation errors, keyed by field name.
"""

from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


class Conflict(APIException):
    """The request is valid but clashes with the resource's current state."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state of the resource."
    default_code = "conflict"


class InvalidSignature(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Invalid webhook signature."
    default_code = "invalid_signature"


def exception_handler(exc, context):
    if isinstance(exc, ProtectedError):
        exc = Conflict("This resource is referenced by existing bookings and cannot be deleted.")

    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # unexpected error: let Django log it and return a 500

    if isinstance(exc, ValidationError):
        error = {
            "code": "validation_error",
            "message": "Invalid request.",
            "details": response.data,
        }
    else:
        detail = response.data.get("detail", "Request failed.")
        error = {"code": getattr(detail, "code", "error"), "message": str(detail)}

    response.data = {"error": error}
    return response
