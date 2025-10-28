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

        # Should contain first + last name combinations (prioritized)
        self.assertIn("José López", input_list)  # Original first + last
        self.assertIn("jose lopez", input_list)  # Normalized first + last

        # Should contain full name (prioritized)
        self.assertIn("José María García López", input_list)
        self.assertIn("jose maria garcia lopez", input_list)

        # Should contain some individual words (may be limited by input size cap)
        # Test that we have at least the most important ones
        self.assertIn("José", input_list)
        self.assertIn("López", input_list)

        # Verify input size is capped
        self.assertLessEqual(len(input_list), 10)

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

    def test_prepare_full_name_suggest_with_non_ascii_names(self):
        """Test that non-ASCII names (like Chinese) are preserved and don't crash"""
        # Create a user with Chinese characters
        chinese_user = User.objects.create_user(
            username="chinese@test.com",
            email="chinese@test.com",
            first_name="李明",
            last_name="王",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(chinese_user)
        input_list = result["input"]

        # Should contain original Chinese characters (most important)
        self.assertIn("李明", input_list)
        self.assertIn("王", input_list)
        self.assertIn("李明 王", input_list)

        # Should NOT crash when ASCII normalization produces empty results
        # The function should gracefully handle this case
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertIn("input", result)
        self.assertIn("weight", result)

        # Verify that we have at least the original name components
        self.assertGreater(
            len(input_list), 0, "Should have at least some input suggestions"
        )

    def test_prepare_full_name_suggest_with_mixed_ascii_non_ascii(self):
        """Test names that mix ASCII and non-ASCII characters"""
        # Create a user with mixed characters
        mixed_user = User.objects.create_user(
            username="mixed@test.com",
            email="mixed@test.com",
            first_name="李小明",
            last_name="Smith",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(mixed_user)
        input_list = result["input"]

        # Should contain original mixed characters
        self.assertIn("李小明", input_list)
        self.assertIn("Smith", input_list)
        self.assertIn("李小明 Smith", input_list)

        # Should contain ASCII normalized version for the ASCII part
        self.assertIn("smith", input_list)
        # Note: The mixed combination might not be generated due to input size limits
        # The important thing is that both parts are preserved

        # Should have first + last combination
        self.assertIn("李小明 Smith", input_list)

    def test_prepare_full_name_suggest_with_arabic_names(self):
        """Test that Arabic names are preserved correctly"""
        # Create a user with Arabic characters
        arabic_user = User.objects.create_user(
            username="arabic@test.com",
            email="arabic@test.com",
            first_name="محمد",
            last_name="أحمد",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(arabic_user)
        input_list = result["input"]

        # Should contain original Arabic characters
        self.assertIn("محمد", input_list)
        self.assertIn("أحمد", input_list)
        self.assertIn("محمد أحمد", input_list)

        # Should NOT crash when ASCII normalization produces empty results
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertIn("input", result)
        self.assertIn("weight", result)

    def test_prepare_full_name_suggest_with_cyrillic_names(self):
        """Test that Cyrillic names work correctly"""
        # Create a user with Cyrillic characters
        cyrillic_user = User.objects.create_user(
            username="cyrillic@test.com",
            email="cyrillic@test.com",
            first_name="Владимир",
            last_name="Путин",
            is_suspended=False,
        )

        result = self.document.prepare_full_name_suggest(cyrillic_user)
        input_list = result["input"]

        # Should contain original Cyrillic characters
        self.assertIn("Владимир", input_list)
        self.assertIn("Путин", input_list)
        self.assertIn("Владимир Путин", input_list)

        # Should NOT crash when ASCII normalization produces empty results
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertIn("input", result)
        self.assertIn("weight", result)
