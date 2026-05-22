import uuid

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.models import Note
from researchhub_access_group.constants import NO_ACCESS, VIEWER
from researchhub_access_group.models import Permission
from researchhub_access_group.query_helpers import unified_document_user_access_q
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Organization
from user.tests.helpers import create_random_authenticated_user


class PermissionHasUserTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("perm_access_user")
        self.unified_document = ResearchhubUnifiedDocument.objects.create()
        self.content_type = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        )
        self.permissions = Permission.objects.filter(
            content_type=self.content_type,
            object_id=self.unified_document.id,
        )

    def test_viewer_grants_access(self):
        Permission.objects.create(
            access_type=VIEWER,
            content_type=self.content_type,
            object_id=self.unified_document.id,
            user=self.user,
        )
        self.assertTrue(self.permissions.has_user(self.user))

    def test_no_access_revokes_even_when_viewer_row_exists(self):
        Permission.objects.create(
            access_type=VIEWER,
            content_type=self.content_type,
            object_id=self.unified_document.id,
            user=self.user,
        )
        Permission.objects.create(
            access_type=NO_ACCESS,
            content_type=self.content_type,
            object_id=self.unified_document.id,
            user=self.user,
        )
        self.assertFalse(self.permissions.has_user(self.user))


class UnifiedDocumentAccessQueryTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("perm_query_user")
        self.organization = Organization.objects.create(name="perm-query-org")
        self.unified_document = ResearchhubUnifiedDocument.objects.create()
        self.content_type = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        )
        self.note = Note.objects.create(
            created_by=self.user,
            organization=self.organization,
            title="restricted note",
            unified_document=self.unified_document,
        )

    def test_revoked_user_excluded_from_note_queryset(self):
        Permission.objects.create(
            access_type=VIEWER,
            content_type=self.content_type,
            object_id=self.unified_document.id,
            user=self.user,
        )
        Permission.objects.create(
            access_type=NO_ACCESS,
            content_type=self.content_type,
            object_id=self.unified_document.id,
            user=self.user,
        )

        visible_ids = set(
            Note.objects.filter(unified_document_user_access_q(self.user)).values_list(
                "id", flat=True
            )
        )
        self.assertNotIn(self.note.id, visible_ids)
