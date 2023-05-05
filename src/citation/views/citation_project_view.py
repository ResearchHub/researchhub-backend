from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from django.db.models import Q

from citation.models import CitationProject
from citation.serializers import CitationProjectSerializer
from user.related_models.organization_model import Organization


class CitationProjectViewSet(ModelViewSet):
    queryset = CitationProject.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = CitationProjectSerializer
    ordering = ["-updated_date"]

    def list(self, request):
        try:
            current_user = request.user
            org_id = request.query_params.get("organization", "")
            if org_id.endswith("/"):
                org_id = org_id[:-1]
            org = Organization.objects.get(id=int(org_id))

            if not org.org_has_user(user=current_user):
                raise PermissionError("Current user not allowed")

            public_project_ids = list(
                org.citation_projects.filter(is_public=True).values_list(
                    "id", flat=True
                )
            )
            non_public_accessible_projs_qs = Q(
                organization=org,
                is_public=False,
                permissions__user=current_user,
            )
            final_citation_proj_qs = CitationProject.objects.filter(
                Q(id__in=public_project_ids) | non_public_accessible_projs_qs
            )
            return Response(self.get_serializer(final_citation_proj_qs, many=True).data)

        except Exception as error:
            return Response(
                error,
                status=status.HTTP_400_BAD_REQUEST,
            )
