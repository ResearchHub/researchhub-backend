from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from citation.models import CitationProject
from citation.serializers import CitationProjectSerializer
from researchhub_access_group.constants import EDITOR
from user.related_models.organization_model import Organization


# TODO: Permissions
class CitationProjectViewSet(ModelViewSet):
    queryset = CitationProject.objects.all()
    filter_backends = (OrderingFilter,)
    permission_classes = [IsAuthenticated]
    serializer_class = CitationProjectSerializer
    ordering = ("created_date",)
    ordering_fields = ("updated_date", "created_date")

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
            citation = self.get_queryset().get(id=response.data.get("id"))
            removed_editors = citation.permissions.filter(
                Q(access_type=EDITOR) & ~Q(id__in=upserted_collaborators)
            ).values_list("user", flat=True)
            citation.remove_editors(removed_editors)
            citation.add_editors(upserted_collaborators)

            citation.refresh_from_db()
            return Response(
                self.get_serializer(citation).data, status=status.HTTP_200_OK
            )

    @action(
        detail=False, methods=["GET"], url_path=r"get_projects/(?P<organization_id>\w+)"
    )
    def get_projects(self, request, organization_id=None):
        user = request.user
        org = Organization.objects.get(id=organization_id)

        if not org.org_has_user(user=user):
            raise PermissionError("Current user not allowed")

        public_projects_query = Q(organization=org, is_public=True, parent=None)
        non_public_accessible_projs_query = Q(
            is_public=False,
            organization=org,
            parent=None,
            permissions__user=user,
        )
        final_citation_proj_qs = self.filter_queryset(
            self.get_queryset().filter(
                public_projects_query | non_public_accessible_projs_query
            )
        )
        return Response(self.get_serializer(final_citation_proj_qs, many=True).data)
