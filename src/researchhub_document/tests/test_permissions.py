from unittest.mock import MagicMock

from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from note.tests.helpers import create_note
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from user.related_models.organization_model import Organization
from user.tests.helpers import create_random_default_user


class HasDocumentEditingPermissionTests(TestCase):
    """Direct unit tests for HasDocumentEditingPermission.has_permission."""

    def setUp(self):
        self.factory = RequestFactory()
        self.permission = HasDocumentEditingPermission()

        self.author = create_random_default_user("perm_author")
        self.moderator = create_random_default_user("perm_moderator", moderator=True)
        self.org_member = create_random_default_user("perm_org_member")
        self.stranger = create_random_default_user("perm_stranger")

        self.organization = Organization.objects.get(user_id=self.author.id)
        Permission.objects.create(
            access_type="MEMBER",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.organization.id,
            user=self.org_member,
        )

        note, _ = create_note(self.author, self.organization)
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.note_post = ResearchhubPost.objects.create(
            created_by=self.author,
            title="Note Post",
            renderable_text="content",
            document_type="DISCUSSION",
            unified_document=uni_doc,
            note=note,
        )

        uni_doc2 = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.plain_post = ResearchhubPost.objects.create(
            created_by=self.author,
            title="Plain Post",
            renderable_text="content",
            document_type="DISCUSSION",
            unified_document=uni_doc2,
        )

    def _make_request(self, user, post_id=None):
        request = self.factory.post("/fake/")
        request.user = user
        request.data = {}
        if post_id is not None:
            request.data["post_id"] = post_id
        return request

    def _view_with_action(self, action):
        view = MagicMock()
        view.action = action
        return view

    def test_author_can_update_own_post(self):
        request = self._make_request(self.author, self.note_post.id)
        view = self._view_with_action("update")
        self.assertTrue(self.permission.has_permission(request, view))

    def test_moderator_can_update_any_post(self):
        request = self._make_request(self.moderator, self.note_post.id)
        view = self._view_with_action("update")
        self.assertTrue(self.permission.has_permission(request, view))

    def test_org_member_can_update_note_based_post(self):
        request = self._make_request(self.org_member, self.note_post.id)
        view = self._view_with_action("update")
        self.assertTrue(self.permission.has_permission(request, view))

    def test_stranger_denied_on_note_based_post(self):
        request = self._make_request(self.stranger, self.note_post.id)
        view = self._view_with_action("update")
        self.assertFalse(self.permission.has_permission(request, view))

    def test_stranger_denied_on_plain_post_without_note(self):
        """Post with no note_id should deny non-author non-moderator."""
        request = self._make_request(self.stranger, self.plain_post.id)
        view = self._view_with_action("update")
        self.assertFalse(self.permission.has_permission(request, view))

    def test_create_without_post_id_always_allowed(self):
        """When no post_id is present, permission is granted (new post creation)."""
        request = self._make_request(self.stranger)
        view = self._view_with_action("create")
        self.assertTrue(self.permission.has_permission(request, view))

    def test_list_action_always_allowed(self):
        """Non-mutating actions bypass the post_id check."""
        request = self._make_request(self.stranger)
        view = self._view_with_action("list")
        self.assertTrue(self.permission.has_permission(request, view))

    def test_author_can_update_plain_post(self):
        request = self._make_request(self.author, self.plain_post.id)
        view = self._view_with_action("update")
        self.assertTrue(self.permission.has_permission(request, view))

    def test_upsert_action_checked(self):
        """The 'upsert' action also triggers the post_id permission check."""
        request = self._make_request(self.stranger, self.plain_post.id)
        view = self._view_with_action("upsert")
        self.assertFalse(self.permission.has_permission(request, view))

    def test_nonexistent_post_raises(self):
        """Referencing a nonexistent post_id should raise DoesNotExist."""
        request = self._make_request(self.author, 999999)
        view = self._view_with_action("update")
        with self.assertRaises(ResearchhubPost.DoesNotExist):
            self.permission.has_permission(request, view)
