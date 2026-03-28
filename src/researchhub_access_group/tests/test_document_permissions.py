import uuid

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from researchhub_access_group.constants import ADMIN, EDITOR, NO_ACCESS, VIEWER
from researchhub_access_group.models import Permission
from researchhub_access_group.permissions import (
    HasAccessPermission,
    HasAdminPermission,
    HasEditingPermission,
    HasOrgEditingPermission,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from note.related_models.note_model import Note
from user.models import User


class _PermissionTestBase(TestCase):
    """Shared setup for document-level permission tests."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.anonymous = AnonymousUser()
        self.admin_user = User.objects.create_user(
            username="admin_user", password=uuid.uuid4().hex
        )
        self.editor_user = User.objects.create_user(
            username="editor_user", password=uuid.uuid4().hex
        )
        self.viewer_user = User.objects.create_user(
            username="viewer_user", password=uuid.uuid4().hex
        )
        self.outsider = User.objects.create_user(
            username="outsider", password=uuid.uuid4().hex
        )

        self.unified_document = ResearchhubUnifiedDocument.objects.create()
        self.note = Note.objects.create(
            title="Test Note",
            created_by=self.admin_user,
            unified_document=self.unified_document,
        )

        ud_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)

        Permission.objects.create(
            access_type=ADMIN,
            content_type=ud_ct,
            object_id=self.unified_document.id,
            user=self.admin_user,
        )
        Permission.objects.create(
            access_type=EDITOR,
            content_type=ud_ct,
            object_id=self.unified_document.id,
            user=self.editor_user,
        )
        Permission.objects.create(
            access_type=VIEWER,
            content_type=ud_ct,
            object_id=self.unified_document.id,
            user=self.viewer_user,
        )

    def _make_request(self, user):
        request = self.factory.get("/api/test/")
        request.user = user
        return request


class HasAdminPermissionTests(_PermissionTestBase):
    def test_admin_user_is_allowed(self):
        request = self._make_request(self.admin_user)
        result = HasAdminPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_editor_user_is_denied(self):
        request = self._make_request(self.editor_user)
        result = HasAdminPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_viewer_user_is_denied(self):
        request = self._make_request(self.viewer_user)
        result = HasAdminPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_outsider_is_denied(self):
        request = self._make_request(self.outsider)
        result = HasAdminPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_object_without_unified_document_raises(self):
        obj = type("FakeObj", (), {})()
        request = self._make_request(self.admin_user)
        with self.assertRaises(Exception):
            HasAdminPermission().has_object_permission(request, None, obj)


class HasEditingPermissionTests(_PermissionTestBase):
    def test_admin_user_is_allowed(self):
        request = self._make_request(self.admin_user)
        result = HasEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_editor_user_is_allowed(self):
        request = self._make_request(self.editor_user)
        result = HasEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_viewer_user_is_denied(self):
        request = self._make_request(self.viewer_user)
        result = HasEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_outsider_is_denied(self):
        request = self._make_request(self.outsider)
        result = HasEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_anonymous_user_is_denied(self):
        request = self._make_request(self.anonymous)
        result = HasEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_object_without_unified_document_raises(self):
        obj = type("FakeObj", (), {})()
        request = self._make_request(self.editor_user)
        with self.assertRaises(Exception):
            HasEditingPermission().has_object_permission(request, None, obj)

    def test_no_access_user_is_denied(self):
        """A user with NO_ACCESS should not get editing permission."""
        no_access_user = User.objects.create_user(
            username="no_access_user", password=uuid.uuid4().hex
        )
        ud_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=NO_ACCESS,
            content_type=ud_ct,
            object_id=self.unified_document.id,
            user=no_access_user,
        )
        request = self._make_request(no_access_user)
        result = HasEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)


class HasOrgEditingPermissionTests(_PermissionTestBase):
    """HasOrgEditingPermission passes perm=False to has_admin_user / has_editor_user,
    disabling per-permission access_type filtering so that any user who has ANY
    non-NO_ACCESS permission record on the document is allowed."""

    def test_admin_user_is_allowed(self):
        request = self._make_request(self.admin_user)
        result = HasOrgEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_editor_user_is_allowed(self):
        request = self._make_request(self.editor_user)
        result = HasOrgEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_viewer_user_is_allowed_via_org_path(self):
        """Viewer is allowed because perm=False disables access_type filtering."""
        request = self._make_request(self.viewer_user)
        result = HasOrgEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_outsider_is_denied(self):
        request = self._make_request(self.outsider)
        result = HasOrgEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_anonymous_user_is_denied(self):
        request = self._make_request(self.anonymous)
        result = HasOrgEditingPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)


class HasAccessPermissionTests(_PermissionTestBase):
    def test_admin_user_has_access(self):
        request = self._make_request(self.admin_user)
        result = HasAccessPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_editor_user_has_access(self):
        request = self._make_request(self.editor_user)
        result = HasAccessPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_viewer_user_has_access(self):
        request = self._make_request(self.viewer_user)
        result = HasAccessPermission().has_object_permission(
            request, None, self.note
        )
        self.assertTrue(result)

    def test_outsider_is_denied(self):
        request = self._make_request(self.outsider)
        result = HasAccessPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)

    def test_anonymous_user_is_denied(self):
        request = self._make_request(self.anonymous)
        result = HasAccessPermission().has_object_permission(
            request, None, self.note
        )
        self.assertFalse(result)
