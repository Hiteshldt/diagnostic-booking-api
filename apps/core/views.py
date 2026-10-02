from django.db import connection
from django.http import JsonResponse


def health(request):
    """Liveness check for load balancers / docker: is the app up and the DB reachable?"""
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
