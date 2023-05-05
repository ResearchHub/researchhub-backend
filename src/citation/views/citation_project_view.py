from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

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

            import pdb; pdb.set_trace()
            public_projects = org.permissions.citation_projects.filter(
                is_public=True
            ).all()
            non_public_accessible_projs = current_user.permissions.filter(
                organization=org,
                is_public=False,
            ).citation_projects.all()
            import pdb

            pdb.set_trace()
        except Exception as error:
            return Response(
                error,
                status=status.HTTP_400_BAD_REQUEST,
            )
