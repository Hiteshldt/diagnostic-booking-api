import logging

from django.db import OperationalError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import InvalidSignature
from apps.core.throttling import ScopedRateThrottle

from . import services, signature
from .models import Payment, WebhookEvent
from .serializers import (
    PaymentCreateSerializer,
    PaymentSerializer,
    WebhookResponseSerializer,
    WebhookSerializer,
)
from .tasks import process_webhook_event

logger = logging.getLogger(__name__)


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payments"

    def get_queryset(self):
        queryset = Payment.objects.all()
        if not self.request.user.is_staff:
            queryset = queryset.filter(booking__user=self.request.user)
        return queryset

    @extend_schema(request=PaymentCreateSerializer, responses={201: PaymentSerializer})
    def create(self, request):
        """
        Pay for a booking. The result is in `status`: a FAILED payment still
        returns 201, because the payment record itself was created.
        """
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.initiate_payment(
            user=request.user,
            booking_id=serializer.validated_data["booking_id"],
            simulate=serializer.validated_data.get("simulate"),
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentWebhookView(APIView):
    """
    Called by the payment provider, not by a logged-in user, so it is
    authenticated by an HMAC signature instead of a JWT.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        request=WebhookSerializer,
        responses={200: WebhookResponseSerializer, 202: WebhookResponseSerializer},
        parameters=[
            OpenApiParameter(
                signature.HEADER, str, OpenApiParameter.HEADER, required=True,
                description="Hex HMAC-SHA256 of the raw request body, keyed with WEBHOOK_SECRET.",
            )
        ],
    )
    def post(self, request):
        # Read the raw bytes first: the signature covers exactly what was sent.
        if not signature.is_valid(request.body, request.headers.get(signature.HEADER)):
            raise InvalidSignature()

        serializer = WebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = {**serializer.validated_data, "payment_id": str(serializer.validated_data["payment_id"])}

        event, _ = services.receive_event(event_id=payload["event_id"], payload=payload)
        duplicate = event.is_final
        accepted = status.HTTP_200_OK

        if not duplicate:
            try:
                event = services.process_event(event.pk)
            except OperationalError:
                # The event is safely stored; let a worker retry applying it.
                logger.warning("webhook processing deferred", extra={"ctx": {"event_id": event.event_id}}, exc_info=True)
                process_webhook_event.delay(event.pk)
                accepted = status.HTTP_202_ACCEPTED

        if event.status == WebhookEvent.Status.FAILED:
            raise NotFound("Payment not found.")

        return Response(
            {"event_id": event.event_id, "status": event.status, "duplicate": duplicate},
            status=accepted,
        )
