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

    def test_prepare_full_name_suggest_with_accented_names(self):
        """Test that accented names are properly normalized for search"""
        # Create a user with accented characters
        accented_user = User.objects.create_user(
            username="martin@test.com",
            email="martin@test.com",
            first_name="Martín",
            last_name="Rivero",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(accented_user)

        # Check that both original and normalized versions are included
        input_list = result["input"]

        # Should contain original accented version
        self.assertIn("Martín", input_list)
        self.assertIn("Rivero", input_list)
        self.assertIn("Martín Rivero", input_list)

        # Should contain normalized ASCII version
        self.assertIn("martin", input_list)
        self.assertIn("rivero", input_list)
        self.assertIn("martin rivero", input_list)

    def test_prepare_full_name_suggest_with_multiple_names(self):
        """Test normalization with multiple name parts"""
        # Create a user with multiple name parts
        multi_name_user = User.objects.create_user(
            username="jose@test.com",
            email="jose@test.com",
            first_name="José María",
            last_name="García López",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(multi_name_user)
        input_list = result["input"]

        # Should contain first + last name combinations
        self.assertIn("José López", input_list)  # Original first + last
        self.assertIn("jose lopez", input_list)  # Normalized first + last

        # Should contain all individual words
        self.assertIn("José", input_list)
        self.assertIn("María", input_list)
        self.assertIn("García", input_list)
        self.assertIn("López", input_list)

        # Should contain normalized versions
        self.assertIn("jose", input_list)
        self.assertIn("maria", input_list)
        self.assertIn("garcia", input_list)
        self.assertIn("lopez", input_list)

    def test_prepare_full_name_suggest_with_special_characters(self):
        """Test normalization with various special characters"""
        # Create a user with various accented characters
        special_user = User.objects.create_user(
            username="special@test.com",
            email="special@test.com",
            first_name="François",
            last_name="Müller",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(special_user)
        input_list = result["input"]

        # Should contain normalized versions
        self.assertIn("francois", input_list)
        self.assertIn("muller", input_list)
        self.assertIn("francois muller", input_list)

        # Should still contain original versions
        self.assertIn("François", input_list)
        self.assertIn("Müller", input_list)
        self.assertIn("François Müller", input_list)

    def test_prepare_full_name_suggest_removes_duplicates(self):
        """Test that duplicate entries are removed from input list"""
        # Create a user where normalization might create duplicates
        duplicate_user = User.objects.create_user(
            username="simple@test.com",
            email="simple@test.com",
            first_name="John",
            last_name="Doe",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(duplicate_user)
        input_list = result["input"]

        # Check that there are no duplicates
        self.assertEqual(
            len(input_list),
            len(set(input_list)),
            "Input list should not contain duplicates",
        )

        # Should contain expected entries
        self.assertIn("John", input_list)
        self.assertIn("Doe", input_list)
        self.assertIn("john", input_list)
        self.assertIn("doe", input_list)
        self.assertIn("John Doe", input_list)
        self.assertIn("john doe", input_list)
