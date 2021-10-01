from django.core.files.base import ContentFile
from django.db.models import Q
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny
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
        methods=['get'],
    )
    def get_organization_templates(self, request, pk=None):
        user = request.user

        if pk == '0':
            templates = self.queryset.filter(
                Q(created_by__id=user.id) |
                Q(is_default=True)
            )
        else:
            templates = self.queryset.filter(
                Q(organization__id=pk) |
                Q(is_default=True)
            )

        serializer = self.serializer_class(templates, many=True)
        return Response(serializer.data, status=200)
