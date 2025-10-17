from django.db.models import Case, CharField, Prefetch, Value, When
from django.db.models.functions import Lower
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from user_lists.models import List, ListItem
from user_lists.permissions import IsOwnerOrReadOnly
from user_lists.serializers import ListItemSerializer, ListSerializer


class _ListBaseViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]

    # Override
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    # Override
    def destroy(self, request, *args, **kwargs):
        self.perform_destroy(self.get_object())

        return Response({"message": "Deleted successfully"}, status=status.HTTP_200_OK)


class ListItemViewSet(_ListBaseViewSet):
    serializer_class = ListItemSerializer

    def get_queryset(self):
        return ListItem.objects.select_related(
            "parent_list", "parent_list__created_by", "unified_document"
        ).filter(parent_list__created_by=self.request.user, is_removed=False)


class ListViewSet(_ListBaseViewSet):
    serializer_class = ListSerializer

    def get_queryset(self):
        return List.objects.for_user(self.request.user).prefetch_related(
            Prefetch(
                "items", queryset=ListItem.objects.select_related("unified_document")
            )
        )

    # Override
    def list(self, request, *args, **kwargs):
        """GET /api/list/ - List all lists with optional ordering"""

        order = request.query_params.get("order")
        qs = self.get_queryset()

        if order:
            if order not in {
                "name",
                "-name",
                "created_date",
                "-created_date",
                "updated_date",
                "-updated_date",
            }:
                return Response(
                    {"error": "Invalid order parameter."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not order:
            order = "name"

        qs = qs.order_by(Lower(order) if "name" in order else order)
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)

        return (
            self.get_paginated_response(ser.data)
            if page is not None
            else Response(ser.data)
        )

    # Override
    def retrieve(self, request, *args, **kwargs):
        """GET /api/list/{id}/ - Get an individual list with optional items ordering"""
        instance = self.get_object()
        items_order = request.query_params.get("items_order")

        if items_order:
            if items_order not in {"created_date", "-created_date", "name", "-name"}:
                return Response(
                    {"error": "Invalid items_order parameter"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if items_order != "-created_date":  # Default
                if items_order in ["name", "-name"]:
                    ordered_items_queryset = self._get_name_ordered_queryset(
                        instance.items, descending=(items_order == "-name")
                    )
                else:
                    ordered_items_queryset = instance.items.order_by(items_order)

                instance = List.objects.prefetch_related(
                    Prefetch("items", queryset=ordered_items_queryset)
                ).get(pk=instance.pk)

        return Response(self.get_serializer(instance).data)

    def _get_name_ordered_queryset(self, queryset, descending=False):
        """
        Create a queryset ordered by document title based on the document type.
        """

        title_expression = Lower(
            Case(
                When(
                    unified_document__document_type="PAPER",
                    then="unified_document__paper__title",
                ),
                When(
                    unified_document__document_type__in=["GRANT", "PREREGISTRATION"],
                    then="unified_document__posts__title",
                ),
                default=Value(""),
                output_field=CharField(),
            )
        )

        order_field = title_expression.desc() if descending else title_expression.asc()

        return (
            queryset.select_related("unified_document__paper")
            .prefetch_related("unified_document__posts")
            .order_by(order_field)
        )
