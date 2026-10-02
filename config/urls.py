from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.bookings.views import BookingViewSet
from apps.centres.views import CentreTestViewSet, CentreViewSet, DiagnosticTestViewSet
from apps.core.views import health
from apps.payments.views import PaymentViewSet, PaymentWebhookView

router = DefaultRouter()
router.register("centres", CentreViewSet, basename="centre")
router.register("tests", DiagnosticTestViewSet, basename="test")
router.register("bookings", BookingViewSet, basename="booking")
router.register("payments", PaymentViewSet, basename="payment")

centre_tests = CentreTestViewSet.as_view({"get": "list", "post": "create"})
centre_test_detail = CentreTestViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("centres/<int:centre_pk>/tests/", centre_tests, name="centre-tests"),
    path(
        "centres/<int:centre_pk>/tests/<int:pk>/",
        centre_test_detail,
        name="centre-test-detail",
    ),
    # Must come before the router, or "webhook" is read as a payment id.
    path("payments/webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("", include(router.urls)),
    path("health/", health, name="health"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]


def _error(code, message, status):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


# Keep errors JSON even when they happen outside a DRF view.
def handler404(request, exception):
    return _error("not_found", "Not found.", 404)


def handler500(request):
    return _error("server_error", "Internal server error.", 500)
