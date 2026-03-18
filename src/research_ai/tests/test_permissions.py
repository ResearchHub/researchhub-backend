from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from research_ai.permissions import ResearchAIPermission
from user.permissions import IsModerator, UserIsEditor
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
    create_random_default_user,
)


class ResearchAIPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission = ResearchAIPermission()

    def test_anonymous_user_denied(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertFalse(request.user.is_authenticated)
        self.assertFalse(self.permission.has_permission(request, None))

    def test_authenticated_user_allowed(self):
        user = create_random_authenticated_user("auth")
        request = self.factory.get("/")
        request.user = user
        self.assertTrue(request.user.is_authenticated)
        self.assertTrue(self.permission.has_permission(request, None))

    def test_is_authorized_anonymous_false(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertFalse(self.permission.is_authorized(request, None, None))

    def test_is_authorized_authenticated_true(self):
        user = create_random_authenticated_user("auth")
        request = self.factory.get("/")
        request.user = user
        self.assertTrue(self.permission.is_authorized(request, None, None))


class UserIsEditorOrModeratorCompositionTests(TestCase):
    """Tests the ``UserIsEditor | IsModerator`` OR-composition used by
    Research AI views since the editor-access PR."""

    def setUp(self):
        self.factory = RequestFactory()
        composed_cls = UserIsEditor | IsModerator
        self.permission = composed_cls()

    def test_anonymous_user_denied(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertFalse(self.permission.has_permission(request, None))

    def test_regular_user_denied(self):
        user = create_random_default_user("regular_perm")
        request = self.factory.get("/")
        request.user = user
        self.assertFalse(self.permission.has_permission(request, None))

    def test_moderator_allowed(self):
        mod = create_random_authenticated_user("mod_perm", moderator=True)
        request = self.factory.get("/")
        request.user = mod
        self.assertTrue(self.permission.has_permission(request, None))

    def test_hub_editor_allowed(self):
        editor, _hub = create_hub_editor("ed_perm", "ed_hub")
        request = self.factory.get("/")
        request.user = editor
        self.assertTrue(self.permission.has_permission(request, None))

    def test_editor_who_is_also_moderator_allowed(self):
        editor, _hub = create_hub_editor("edmod", "edmod_hub", moderator=True)
        request = self.factory.get("/")
        request.user = editor
        self.assertTrue(self.permission.has_permission(request, None))
