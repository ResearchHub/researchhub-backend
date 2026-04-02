from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from ai_peer_review.permissions import AIPeerReviewPermission


class AIPeerReviewPermissionTests(SimpleTestCase):
    def test_has_object_permission_unknown_type_uses_super_safe_method(self):
        perm = AIPeerReviewPermission()
        request = RequestFactory().get("/")
        user = type("U", (), {"is_authenticated": True})()
        request.user = user
        view = MagicMock()
        self.assertTrue(perm.has_object_permission(request, view, object()))

    def test_has_permission_requires_authentication(self):
        perm = AIPeerReviewPermission()
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        self.assertFalse(perm.has_permission(request, MagicMock()))
