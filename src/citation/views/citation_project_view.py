from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from citation.models import CitationProject
from citation.serializers import CitationProjectSerializer
from researchhub_access_group.constants import EDITOR
from user.related_models.organization_model import Organization


class CitationProjectViewSet(ModelViewSet):
    queryset = CitationProject.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = CitationProjectSerializer
    ordering = ["created_date"]

    def create(self, request, *args, **kwargs):
        upserted_collaborators = request.data.get("collaborators")
        with transaction.atomic():
            response = self.super().create(request, *args, **kwargs)
            citation = self.get_queryset().get(id=response.data.get("id"))
            citation.set_creator_as_admin()
            citation.add_editors(upserted_collaborators)

            citation.refresh_from_db()
            return Response(
                self.get_serializer(citation).data, status=status.HTTP_200_OK
            )

    def update(self, request, *args, **kwargs):
        upserted_collaborators = request.data.get("collaborators")
        with transaction.atomic():
            response = self.super().update(request, *args, **kwargs)
            citation = CitationProject.objects.get(id=response.data.get("id"))
            removed_editors = citation.permissions.filter(
                Q(access_type=EDITOR) & ~Q(id__in=upserted_collaborators)
            ).values_list("user", flat=True)
            citation.remove_editors(removed_editors)
            citation.add_editors(upserted_collaborators)

            citation.refresh_from_db()
            return Response(
                self.get_serializer(citation).data, status=status.HTTP_200_OK
            )

    def list(self, request):
        try:
            current_user = request.user
            org_id = request.query_params.get("organization", None)

            if org_id.endswith("/"):
                org_id = org_id[:-1]
            org = Organization.objects.get(id=int(org_id))

            if not org.org_has_user(user=current_user):
                raise PermissionError("Current user not allowed")

            public_project_ids = list(
                org.citation_projects.filter(is_public=True, parent=None).values_list(
                    "id",
                    flat=True,
                )
            )
            non_public_accessible_projs_qs = Q(
                is_public=False,
                organization=org,
                parent=None,
                permissions__user=current_user,
            )
            final_citation_proj_qs = (
                CitationProject.objects.filter(
                    Q(id__in=public_project_ids) | non_public_accessible_projs_qs
                )
                .order_by(*self.ordering)
                .distinct()
            )
            return Response(self.get_serializer(final_citation_proj_qs, many=True).data)

        except Exception as error:
            return Response(
                error,
                status=status.HTTP_400_BAD_REQUEST,
            )

    # @action(detail=True, methods=["POST"], permission_classes=[IsAuthenticated])
    # def upsert(self, request, pk=None, *args, **kwargs):
    #     # with transaction.atomic:
    #     is_create = int(pk) == 0
    #     respective_model_method = super().create if is_create else super().update
    #     response = respective_model_method(request, *args, **kwargs)
    #     upserted_citation = CitationProject.objects.get(id=response.data.get("id"))

    #     upserted_collaborators = request.data.get("collaborators")
    #     if is_create:
    #         upserted_citation.set_creator_as_admin()
    #         upserted_citation.add_editors(upserted_collaborators)
    #     else:
    #         removed_editors = upserted_citation.permissions.filter(
    #             Q(access_type=EDITOR) & ~Q(id__in=upserted_collaborators)
    #         ).values_list("user", flat=True)
    #         upserted_citation.remove_editors(removed_editors)
    #         upserted_citation.add_editors(upserted_collaborators)

    #     upserted_citation.refresh_from_db()

    #     return Response(
    #         self.get_serializer(upserted_citation).data, status=status.HTTP_200_OK
    #     )
