from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import services
from .models import Booking
from .serializers import BookingCreateSerializer, BookingSerializer


class BookingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BookingSerializer

    def get_queryset(self):
        queryset = Booking.objects.select_related("centre_test__centre", "centre_test__test")
        # Users only ever see their own bookings. Asking for someone else's
        # returns 404 rather than 403, so we never confirm that an id exists.
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)

        wanted = self.request.query_params.get("status")
        if wanted is not None:
            if wanted not in Booking.Status.values:
                raise ValidationError({"status": f"Must be one of {', '.join(Booking.Status.values)}."})
            queryset = queryset.filter(status=wanted)
        return queryset

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=Booking.Status.values)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=BookingCreateSerializer, responses={201: BookingSerializer})
    def create(self, request):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_booking(
            user=request.user,
            centre_test=serializer.validated_data["centre_test"],
            appointment_at=serializer.validated_data["appointment_at"],
        )
        return Response(self._render(booking.pk), status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=BookingSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()  # 404 unless it belongs to the caller
        services.cancel_booking(booking.pk)
        return Response(self._render(booking.pk))

    def _render(self, pk):
        return BookingSerializer(self.get_queryset().get(pk=pk)).data
