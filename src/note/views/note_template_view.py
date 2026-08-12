from django.core.files.base import ContentFile
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from note.models import NoteTemplate
from note.serializers import NoteTemplateSerializer
from user.models import Organization


class NoteTemplateViewSet(ModelViewSet):
    ordering = "-created_date"
    queryset = NoteTemplate.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = NoteTemplateSerializer
    http_method_names = ["get", "head", "options", "post"]

    def get_queryset(self):
        user = self.request.user
        return (
            self.queryset.filter(
                Q(is_default=True)
                | Q(created_by=user)
                | Q(organization__permissions__user=user)
            )
            .filter(is_removed=False)
            .distinct()
            .order_by("-created_date")
        )

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        name = data.get("name", "Template")
        organization_id = data.get("organization", None)
        is_default = data.get("is_default", False)
        src = data.get("full_src", "")

        if organization_id:
            created_by = None
            organization = Organization.objects.get(id=organization_id)
            if not (
                organization.org_has_admin_user(user)
                or organization.org_has_member_user(user)
            ):
                return Response({"data": "Invalid permissions"}, status=403)
        else:
            created_by = user
            organization = None

        note_template = NoteTemplate.objects.create(
            created_by=created_by,
            is_default=is_default,
            name=name,
            organization=organization,
        )
        file_name, file = self._create_src_content_file(note_template, src)
        note_template.src.save(file_name, file)
        serializer = self.serializer_class(note_template)
        data = serializer.data
        return Response(data, status=200)

    def _create_src_content_file(self, template, data):
        file_name = f"NOTE-TEMPLATE-{template.id}--TITLE-{template.name}.txt"
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file

    @action(detail=True, methods=["post", "delete"])
    def delete(self, request, pk=None):
        template = self.get_object()

        if template.is_default or not self._can_delete(request.user, template):
            status_code = 403
        else:
            template.is_removed = True
            template.save()
            status_code = 200

        serializer = self.serializer_class(template)
        return Response(serializer.data, status=status_code)

    def _can_delete(self, user, template):
        # Mirrors the create authorization: creator, or org admin/member.
        if template.created_by == user:
            return True
        organization = template.organization
        return organization is not None and (
            organization.org_has_admin_user(user)
            or organization.org_has_member_user(user)
        )
