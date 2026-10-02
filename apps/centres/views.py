import json

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from apps.core.exceptions import Conflict
from apps.core.permissions import IsAdminOrReadOnly

from . import cache
from .models import CentreTest, DiagnosticCentre, DiagnosticTest
from .serializers import CentreSerializer, CentreTestSerializer, DiagnosticTestSerializer

WRITE_METHODS = ["get", "post", "patch", "delete", "head", "options"]


class CentreViewSet(viewsets.ModelViewSet):
    """
    Diagnostic centres with the tests they offer. Public to read, admin-only to
    change. Reads are served from the cache.
    """

    serializer_class = CentreSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [SearchFilter]
    search_fields = ["name", "location"]
    http_method_names = WRITE_METHODS

    def get_queryset(self):
        # prefetch: load every centre's tests in 2 queries total instead of 1 per centre
        available = CentreTest.objects.filter(is_available=True).select_related("test")
        queryset = DiagnosticCentre.objects.prefetch_related(Prefetch("offerings", queryset=available))

        test_id = self.request.query_params.get("test")
        if test_id is not None:
            if not test_id.isdigit():
                raise ValidationError({"test": "Must be a test id."})
            queryset = queryset.filter(offerings__test_id=test_id, offerings__is_available=True)
        return queryset

    @extend_schema(parameters=[OpenApiParameter("test", int, description="Only centres offering this test id")])
    def list(self, request, *args, **kwargs):
        return self._cached(request, super().list, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        return self._cached(request, super().retrieve, *args, **kwargs)

    def _cached(self, request, handler, *args, **kwargs):
        url = request.build_absolute_uri()
        data = cache.get_cached(url)
        if data is None:
            response = handler(request, *args, **kwargs)
            # Round-trip through JSON so we cache plain dicts/lists, not serializer objects.
            data = json.loads(JSONRenderer().render(response.data))
            cache.set_cached(url, data)
        return Response(data)


class DiagnosticTestViewSet(viewsets.ModelViewSet):
    """The catalogue of diagnostic tests. Public to read, admin-only to change."""

    queryset = DiagnosticTest.objects.all()
    serializer_class = DiagnosticTestSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [SearchFilter]
    search_fields = ["name"]
    http_method_names = WRITE_METHODS


class CentreTestViewSet(viewsets.ModelViewSet):
    """The tests one centre offers: /centres/{centre_pk}/tests/."""

    serializer_class = CentreTestSerializer
    permission_classes = [IsAdminOrReadOnly]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no URL kwargs
            return CentreTest.objects.none()
        centre = get_object_or_404(DiagnosticCentre, pk=self.kwargs["centre_pk"])
        return centre.offerings.select_related("test")

    def perform_create(self, serializer):
        centre = get_object_or_404(DiagnosticCentre, pk=self.kwargs["centre_pk"])
        if centre.offerings.filter(test=serializer.validated_data["test"]).exists():
            raise Conflict("This centre already offers this test. Update its price instead.")
        serializer.save(centre=centre)

    def perform_update(self, serializer):
        new_test = serializer.validated_data.get("test")
        if new_test and new_test != serializer.instance.test:
            raise ValidationError({"test_id": "The test of an existing offering cannot be changed."})
        serializer.save()
