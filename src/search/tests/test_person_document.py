from unittest.mock import Mock

from django.test import TestCase

from search.documents.person import PersonDocument


class PersonDocumentTests(TestCase):
    def test_prepare_suggestion_phrases_with_institutions(self):
        """Test suggestion phrases include author name + institution combinations"""
        # Minimal mock setup
        document = PersonDocument()

        # Mock author with institutions
        author = Mock()
        author.full_name = "John Doe"
        author.first_name = "John"
        author.last_name = "Doe"
        author.user = Mock()  # has user (weight 15)

        # Mock institution
        institution = Mock()
        institution.display_name = "Stanford University"

        author_institution = Mock()
        author_institution.institution = institution

        author.institutions.all.return_value = [author_institution]

        # Execute
        result = document.prepare_suggestion_phrases(author)

        # Verify - check that line 104's output is present
        expected_combo = {"input": "John Stanford University", "weight": 3}
        self.assertIn(expected_combo, result)

        # Also verify other suggestions are present
        self.assertIn({"input": "John Doe", "weight": 15}, result)
        self.assertIn({"input": "John", "weight": 5}, result)
        self.assertIn({"input": "Doe", "weight": 5}, result)
        self.assertIn({"input": "Stanford University", "weight": 3}, result)

    def test_prepare_suggestion_phrases_without_institutions(self):
        """Test suggestion phrases work without institutions"""
        document = PersonDocument()
        author = Mock()
        author.full_name = "Jane Smith"
        author.first_name = "Jane"
        author.last_name = "Smith"
        author.user = None  # no user (weight 10)
        author.institutions.all.return_value = []

        result = document.prepare_suggestion_phrases(author)

        # Verify basic suggestions without institutions
        self.assertIn({"input": "Jane Smith", "weight": 10}, result)
        self.assertIn({"input": "Jane", "weight": 5}, result)
        self.assertIn({"input": "Smith", "weight": 5}, result)
        self.assertEqual(len(result), 3)

    def test_prepare_person_types_with_user(self):
        """
        Test person types includes user when user exists.
        """
        # Arrange
        document = PersonDocument()
        author = Mock()
        author.user = Mock()

        # Act
        result = document.prepare_person_types(author)

        # Assert
        self.assertEqual(result, ["author", "user"])

    def test_prepare_person_types_without_user(self):
        """
        Test person types excludes 'user' when user doesn't exist.
        """
        # Arrange
        document = PersonDocument()
        author = Mock()
        author.user = None

        # Act
        result = document.prepare_person_types(author)

        # Assert
        self.assertEqual(result, ["author"])

    def test_prepare_institutions(self):
        """
        Test institutions preparation.
        """
        # Arrange
        document = PersonDocument()
        author = Mock()
        institution = Mock()
        institution.id = 1
        institution.display_name = "Stanford University"
        author_institution = Mock()
        author_institution.institution = institution
        author.institutions = Mock()
        author.institutions.all.return_value = [author_institution]

        # Act
        result = document.prepare_institutions(author)

        # Assert
        self.assertEqual(result, [{"id": 1, "name": "Stanford University"}])

    def test_prepare_user_reputation_with_user(self):
        """
        Test user reputation returns reputation when user exists.
        """
        # Arrange
        document = PersonDocument()
        author = Mock()
        author.user = Mock()
        author.user.reputation = 1500

        # Act
        result = document.prepare_user_reputation(author)

        # Assert
        self.assertEqual(result, 1500)

    def test_prepare_user_reputation_without_user(self):
        """
        Test user reputation returns 0 when user doesn't exist.
        """
        # Arrange
        document = PersonDocument()
        author = Mock()
        author.user = None

        # Act
        result = document.prepare_user_reputation(author)

        # Assert
        self.assertEqual(result, 0)
