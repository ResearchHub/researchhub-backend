from django.core.files.base import ContentFile
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny
)
from researchhub_access_group.permissions import (
    HasEditingPermission,
    HasOrgEditingPermission,
)

from note.models import NoteTemplate
from note.serializers import NoteTemplateSerializer
from user.models import Organization


class NoteTemplateViewSet(ModelViewSet):
    ordering = ('-created_date')
    queryset = NoteTemplate.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = NoteTemplateSerializer

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        name = data.get('name', 'Template')
        organization_id = data.get('organization', None)
        is_default = data.get('is_default', False)
        src = data.get('full_src', '')

        if organization_id:
            created_by = None
            organization = Organization.objects.get(id=organization_id)
            if not (
                organization.org_has_admin_user(user) or
                organization.org_has_member_user(user)
            ):
                return Response({'data': 'Invalid permissions'}, status=403)
        else:
            created_by = user
            organization = None

        note_template = NoteTemplate.objects.create(
            created_by=created_by,
            is_default=is_default,
            name=name,
            organization=organization,
        )
        file_name, file = self._create_src_content_file(
            note_template,
            src
        )
        note_template.src.save(file_name, file)
        serializer = self.serializer_class(note_template)
        data = serializer.data
        return Response(data, status=200)

    def _create_src_content_file(self, template, data):
        file_name = f'NOTE-TEMPLATE-{template.id}--TITLE-{template.name}.txt'
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file

    @action(
        detail=True,
        methods=['post', 'delete'],
        permission_classes=[
            HasOrgEditingPermission | HasEditingPermission
        ]
    )
    def delete(self, request, pk=None):
        template = NoteTemplate.objects.get(id=pk)

        if template.is_default:
            status_code = 403
        else:
            template.is_removed = True
            template.save()
            status_code = 200

        serializer = self.serializer_class(template)
        return Response(serializer.data, status=status_code)
