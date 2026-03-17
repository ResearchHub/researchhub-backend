from unittest.mock import MagicMock, PropertyMock, patch

from django.test import RequestFactory, TestCase

from note.models import Note
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from user.related_models.organization_model import Organization
from user.tests.helpers import create_random_default_user


class HasDocumentEditingPermissionTests(TestCase):
    """Unit tests for HasDocumentEditingPermission.

    Covers the bug fix where accessing ``post.note.organization`` crashed when
    ``note_id`` was ``None``.  The permission must now return ``False`` for
    non-author/non-moderator when the post has no linked note instead of
    raising an ``AttributeError``.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.permission = HasDocumentEditingPermission()

        self.author = create_random_default_user("perm_author")
        self.moderator = create_random_default_user("perm_mod", moderator=True)
        self.stranger = create_random_default_user("perm_stranger")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.post = ResearchhubPost.objects.create(
            created_by=self.author,
            title="Test Post",
            renderable_text="Body",
            document_type="DISCUSSION",
            unified_document=self.unified_doc,
        )

    def _make_view(self, action):
        view = MagicMock()
        view.action = action
        return view

    def _make_request(self, user, method="PUT", post_id=None):
        request = self.factory.generic(method, "/")
        request.user = user
        request.data = {}
        if post_id is not None:
            request.data["post_id"] = post_id
        return request

    # --- Actions that bypass the permission check ---

    def test_list_action_returns_true(self):
        view = self._make_view("list")
        request = self._make_request(self.stranger)
        self.assertTrue(self.permission.has_permission(request, view))

    def test_retrieve_action_returns_true(self):
        view = self._make_view("retrieve")
        request = self._make_request(self.stranger)
        self.assertTrue(self.permission.has_permission(request, view))

    def test_destroy_action_returns_true(self):
        view = self._make_view("destroy")
        request = self._make_request(self.stranger)
        self.assertTrue(self.permission.has_permission(request, view))

    # --- Create / update without post_id (new post) ---

    def test_create_without_post_id_returns_true(self):
        view = self._make_view("create")
        request = self._make_request(self.stranger)
        self.assertTrue(self.permission.has_permission(request, view))

    # --- Update existing post: author and moderator access ---

    def test_update_by_author_returns_true(self):
        view = self._make_view("update")
        request = self._make_request(self.author, post_id=self.post.id)
        self.assertTrue(self.permission.has_permission(request, view))

    def test_update_by_moderator_returns_true(self):
        view = self._make_view("update")
        request = self._make_request(self.moderator, post_id=self.post.id)
        self.assertTrue(self.permission.has_permission(request, view))

    def test_upsert_by_author_returns_true(self):
        view = self._make_view("upsert")
        request = self._make_request(self.author, post_id=self.post.id)
        self.assertTrue(self.permission.has_permission(request, view))

    # --- Bug fix: post without note_id ---

    def test_update_by_stranger_on_post_without_note_returns_false(self):
        """The fixed code path: when note_id is None, non-author/non-mod gets
        False rather than an AttributeError."""
        self.assertIsNone(self.post.note_id)
        view = self._make_view("update")
        request = self._make_request(self.stranger, post_id=self.post.id)
        self.assertFalse(self.permission.has_permission(request, view))

    def test_create_by_stranger_on_post_without_note_returns_false(self):
        self.assertIsNone(self.post.note_id)
        view = self._make_view("create")
        request = self._make_request(self.stranger, post_id=self.post.id)
        self.assertFalse(self.permission.has_permission(request, view))

    # --- Post with note: org membership ---

    def _create_note_for_post(self, org):
        note_ud = ResearchhubUnifiedDocument.objects.create(
            document_type="NOTE"
        )
        note = Note.objects.create(
            created_by=self.author,
            organization=org,
            title="A Note",
            unified_document=note_ud,
        )
        self.post.note = note
        self.post.save(update_fields=["note"])
        return note

    def test_update_by_org_member_with_note_returns_true(self):
        org = Organization.objects.create(name="TestOrg")
        self._create_note_for_post(org)

        with patch.object(
            Organization, "org_has_member_user", return_value=True
        ) as mock_member:
            view = self._make_view("update")
            request = self._make_request(self.stranger, post_id=self.post.id)
            self.assertTrue(self.permission.has_permission(request, view))
            mock_member.assert_called_once_with(self.stranger)

    def test_update_by_non_member_with_note_returns_false(self):
        org = Organization.objects.create(name="TestOrg2")
        self._create_note_for_post(org)

        with patch.object(
            Organization, "org_has_member_user", return_value=False
        ):
            view = self._make_view("update")
            request = self._make_request(self.stranger, post_id=self.post.id)
            self.assertFalse(self.permission.has_permission(request, view))
