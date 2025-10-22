from django.test import TestCase

from search.documents.user import UserDocument
from user.models import User


class UserDocumentTests(TestCase):
    def setUp(self):
        self.document = UserDocument()
        # Create test users
        self.active_user = User.objects.create_user(
            username="active@test.com",
            email="active@test.com",
            first_name="Active",
            last_name="User",
            is_suspended=False,
        )
        self.suspended_user = User.objects.create_user(
            username="suspended@test.com",
            email="suspended@test.com",
            first_name="Suspended",
            last_name="User",
            is_suspended=True,
        )

    def test_should_index_object_active_user(self):
        """Test that active users should be indexed"""
        result = self.document.should_index_object(self.active_user)
        self.assertTrue(result, "Active users should be indexed")

    def test_should_index_object_suspended_user(self):
        """Test that suspended users should not be indexed"""
        result = self.document.should_index_object(self.suspended_user)
        self.assertFalse(result, "Suspended users should not be indexed")
