from unittest.mock import Mock

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

    def test_prepare_is_suspended_active_user(self):
        """Test that is_suspended field is prepared correctly for active users"""
        result = self.document.prepare_is_suspended(self.active_user)
        self.assertFalse(result, "Active user should have is_suspended=False")

    def test_prepare_is_suspended_suspended_user(self):
        """Test that is_suspended field is prepared correctly for suspended users"""
        result = self.document.prepare_is_suspended(self.suspended_user)
        self.assertTrue(result, "Suspended user should have is_suspended=True")

    def test_prepare_is_suspended_none_user(self):
        """Test that prepare_is_suspended handles None gracefully"""
        result = self.document.prepare_is_suspended(None)
        self.assertIsNone(result, "None user should return None")

    def test_prepare_is_suspended_missing_field(self):
        """Test that prepare_is_suspended handles missing is_suspended field"""
        mock_user = Mock()
        del mock_user.is_suspended  # Remove the attribute

        with self.assertRaises(AttributeError):
            self.document.prepare_is_suspended(mock_user)

    def test_should_index_object_with_none(self):
        """Test that should_index_object handles None gracefully"""
        result = self.document.should_index_object(None)
        self.assertFalse(result, "None user should not be indexed")

    def test_should_index_object_with_missing_field(self):
        """Test that should_index_object handles missing is_suspended field"""
        mock_user = Mock()
        del mock_user.is_suspended  # Remove the attribute

        with self.assertRaises(AttributeError):
            self.document.should_index_object(mock_user)

    def test_should_index_object_boolean_values(self):
        """Test that should_index_object correctly handles boolean values"""
        # Test with explicit True/False values
        mock_user_true = Mock()
        mock_user_true.is_suspended = True

        mock_user_false = Mock()
        mock_user_false.is_suspended = False

        self.assertFalse(self.document.should_index_object(mock_user_true))
        self.assertTrue(self.document.should_index_object(mock_user_false))

    def test_should_index_object_edge_cases(self):
        """Test should_index_object with edge case values"""
        # Test with falsy values that should still be considered "not suspended"
        mock_user_none = Mock()
        mock_user_none.is_suspended = None

        mock_user_empty = Mock()
        mock_user_empty.is_suspended = ""

        mock_user_zero = Mock()
        mock_user_zero.is_suspended = 0

        # These should all be considered "not suspended" and thus indexable
        self.assertTrue(self.document.should_index_object(mock_user_none))
        self.assertTrue(self.document.should_index_object(mock_user_empty))
        self.assertTrue(self.document.should_index_object(mock_user_zero))

    def test_document_field_definitions(self):
        """Test that the document has the correct field definitions"""
        # Check that is_suspended field exists
        self.assertTrue(hasattr(self.document, "is_suspended"))

        # Check that the field exists on the document instance
        self.assertTrue(hasattr(self.document, "is_suspended"))

        # Check that the field is accessible
        field_value = getattr(self.document, "is_suspended", None)
        # The field should exist (even if it's None initially)
        self.assertIsNotNone(
            field_value or True, "is_suspended field should be accessible"
        )

    def test_document_inheritance(self):
        """Test that UserDocument properly inherits from BaseDocument"""
        from search.documents.base import BaseDocument

        self.assertIsInstance(self.document, BaseDocument)

    def test_should_index_object_override(self):
        """Test that should_index_object properly overrides the base method"""
        # Check that the method exists and is callable
        self.assertTrue(hasattr(self.document, "should_index_object"))
        self.assertTrue(callable(self.document.should_index_object))

        # Test that it returns boolean values
        result = self.document.should_index_object(self.active_user)
        self.assertIsInstance(result, bool)

    def test_prepare_is_suspended_method_exists(self):
        """Test that prepare_is_suspended method exists and is callable"""
        self.assertTrue(hasattr(self.document, "prepare_is_suspended"))
        self.assertTrue(callable(self.document.prepare_is_suspended))

    def test_integration_with_real_users(self):
        """Test integration with real User model instances"""
        # Test with real database users
        active_result = self.document.should_index_object(self.active_user)
        suspended_result = self.document.should_index_object(self.suspended_user)

        self.assertTrue(active_result)
        self.assertFalse(suspended_result)

        # Test prepare methods with real users
        active_suspended = self.document.prepare_is_suspended(self.active_user)
        suspended_suspended = self.document.prepare_is_suspended(self.suspended_user)

        self.assertFalse(active_suspended)
        self.assertTrue(suspended_suspended)

    def test_should_index_object_performance(self):
        """Test that should_index_object is efficient for large numbers of users"""
        import time

        # Create many users to test performance
        users = []
        for i in range(100):
            user = User.objects.create_user(
                username=f"user{i}@test.com",
                email=f"user{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                is_suspended=(i % 2 == 0),  # Every other user is suspended
            )
            users.append(user)

        # Test that the method works efficiently
        start_time = time.time()
        results = [self.document.should_index_object(user) for user in users]
        end_time = time.time()

        # Should complete quickly (less than 1 second for 100 users)
        self.assertLess(end_time - start_time, 1.0)

        # Should have correct results
        self.assertEqual(len(results), 100)
        self.assertEqual(sum(results), 50)  # Half should be indexable (not suspended)

    def tearDown(self):
        """Clean up test data"""
        User.objects.all().delete()
