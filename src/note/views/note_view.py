from django.core.files.base import ContentFile
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny
)
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action

from hub.models import Hub
from note.models import (
    Note,
    NoteContent
)
from note.serializers import NoteSerializer, NoteContentSerializer
from researchhub_access_group.models import ResearchhubAccessGroup
from researchhub_document.models import (
    ResearchhubUnifiedDocument
)
from researchhub_document.related_models.constants.document_type import (
    NOTE
)
from user.models import Organization


class NoteViewSet(ModelViewSet):
    ordering = ('-created_date')
    queryset = Note.objects.all()
    permission_classes = [AllowAny]
    serializer_class = NoteSerializer

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        created_by = None
        organization = data.get('organization', None)
        title = data.get('title', '')

        if not organization:
            created_by = user
        else:
            organization = Organization.objects.get(id=organization)

        access_group = self._create_access_group(created_by, organization)
        unified_doc = self._create_unified_doc(request, access_group)
        note = Note.objects.create(
            created_by=created_by,
            organization=organization,
            unified_document=unified_doc,
            title=title,
        )
        serializer = self.serializer_class(note)
        data = serializer.data
        return Response(data, status=200)

    def _create_unified_doc(self, request, access_group):
        data = request.data
        hubs = Hub.objects.filter(
            id__in=data.get('hubs', [])
        ).all()
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=NOTE,
            access_group=access_group,
        )
        unified_doc.hubs.add(*hubs)
        unified_doc.save()
        return unified_doc

    def _create_access_group(self, creator, organization):
        if organization:
            # This copies the access group
            access_group = organization.access_group
            access_group.pk = None
            access_group.save()
            return access_group

        access_group = ResearchhubAccessGroup.objects.create()
        access_group.admins.add(creator)
        return access_group

    def _get_context(self):
        context = {
        }
        return context


class NoteContentViewSet(ModelViewSet):
    ordering = ('-created_date')
    queryset = NoteContent.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = NoteContentSerializer

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        src = data.get('full_src', '')
        note = data.get('note', None)
        plain_text = data.get('plain_text', None)

        note_content = NoteContent.objects.create(
            note_id=note,
            plain_text=plain_text
        )
        file_name, file = self._create_src_content_file(
            note_content,
            src,
            user
        )
        note_content.src.save(file_name, file)
        serializer = self.serializer_class(note_content)
        data = serializer.data
        return Response(data, status=200)

    def _create_src_content_file(self, note, data, user):
        file_name = f'NOTE-CONTENT-{note}--USER-{user.id}.txt'
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file
