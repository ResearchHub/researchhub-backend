from django.db import transaction
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.amplitude import track_event
from citation.models import CitationProject
from citation.permissions import UserIsAdminOfProject
from citation.serializers import CitationProjectSerializer
from researchhub_access_group.constants import EDITOR, VIEWER
from user.related_models.organization_model import Organization


# TODO: Permissions
class CitationProjectViewSet(ModelViewSet):
    queryset = CitationProject.objects.all()
    filter_backends = (OrderingFilter,)
    permission_classes = [IsAuthenticated]
    serializer_class = CitationProjectSerializer
    ordering_fields = ("created_date", "created_date")

    @track_event
    def create(self, request, *args, **kwargs):
        upserted_collaborators = request.data.get("collaborators")
        with transaction.atomic():
            response = super().create(request, *args, **kwargs)
            project = self.get_queryset().get(id=response.data.get("id"))
            project.set_creator_as_admin()
            # project.add_editors(upserted_collaborators.get("editors", []))
            # project.add_viewers(upserted_collaborators.get("viewers", []))
            suffix = get_random_string(length=32)
            slug = slugify(project.project_name)
            if not slug:
                slug = f"{slug}-{suffix}"
            if not CitationProject.objects.filter(slug=slug).exists():
                project.slug = slug
            else:
                project.slug = f"{slug}-{suffix}"
            project.save()

            parent_names = project.get_parent_name(project, [], [])
            project.parent_names = parent_names
            project.save()

            project.refresh_from_db()
            return Response(
                self.get_serializer(project).data, status=status.HTTP_200_OK
            )

    def list(self, request):
        return Response(
            "Method not allowed. Use get_projects instead",
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        upserted_collaborators = request.data.get("collaborators", {})
        # upserted_editors = upserted_collaborators.get("editors", [])
        # upserted_viewers = upserted_collaborators.get("viewers", [])
        with transaction.atomic():
            response = super().update(request, *args, **kwargs)
            project = self.get_queryset().get(id=response.data.get("id"))

            removed_editors = project.permissions.filter(
                Q(access_type=EDITOR) & ~Q(id__in=upserted_editors)
            ).values_list("user", flat=True)
            removed_viewers = project.permissions.filter(
                Q(access_type=VIEWER) & ~Q(id__in=upserted_viewers)
            ).values_list("user", flat=True)

            project.remove_editors(removed_editors)
            project.remove_viewers(removed_viewers)
            project.add_editors(upserted_editors)
            project.add_viewers(upserted_viewers)

            project.refresh_from_db()
            return Response(
                self.get_serializer(project).data, status=status.HTTP_200_OK
            )

    @action(
        detail=False, methods=["GET"], url_path=r"get_projects/(?P<organization_id>\w+)"
    )
    def get_projects(self, request, organization_id=None):
        user = request.user
        org = Organization.objects.get(id=organization_id)

        if not org.org_has_user(user=user):
            raise PermissionError("Current user not allowed")

        public_projects_query = Q(organization=org, parent=None, is_public=True) & ~Q(
            status="no_access"
        )
        non_public_accessible_projs_query = Q(
            is_public=False,
            organization=org,
            parent=None,
            permissions__user=user,
        )
        my_no_access_queries = Q(
            organization=org, parent=None, status="no_access", created_by=user
        )
        final_citation_proj_qs = (
            self.filter_queryset(
                self.get_queryset().filter(
                    public_projects_query
                    | non_public_accessible_projs_query
                    | my_no_access_queries
                )
            )
            .order_by(*self.ordering_fields)
            .distinct()
        )
        return Response(self.get_serializer(final_citation_proj_qs, many=True).data)

    @action(
        detail=True,
        methods=["POST", "DELETE"],
        permission_classes=[UserIsAdminOfProject],
    )
    def remove(self, request, pk=None, *args, **kwargs):
        target_project = self.get_object()
        target_project.delete()
        return Response("removed", status=status.HTTP_200_OK)
