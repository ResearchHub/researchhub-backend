from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from research_ai.permissions import ResearchAIBudgetPermission, ResearchAIPermission
from user.tests.helpers import create_random_authenticated_user


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


class ResearchAIBudgetPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission = ResearchAIBudgetPermission()

    def test_authenticated_default_user_is_allowed(self):
        # Arrange
        request = self.factory.get("/")
        request.user = create_random_authenticated_user("budget-permission")

        # Act / Assert
        self.assertTrue(self.permission.has_permission(request, None))

    def test_blocked_user_is_denied_without_changing_legacy_permission(self):
        # Arrange
        request = self.factory.get("/")
        request.user = create_random_authenticated_user("blocked-budget-permission")
        request.user.probable_spammer = True
        request.user.save(update_fields=["probable_spammer"])

        # Act / Assert
        self.assertFalse(self.permission.has_permission(request, None))
        self.assertTrue(ResearchAIPermission().has_permission(request, None))
