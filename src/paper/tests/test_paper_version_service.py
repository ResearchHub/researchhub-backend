from unittest.mock import Mock

from django.test import TestCase

from paper.related_models.paper_version import PaperVersion
from paper.services.paper_version_service import PaperService
from paper.tests.helpers import create_paper


class PaperServiceTests(TestCase):
    def setUp(self):
        """Set up test data for paper version service tests."""
        # Create original paper
        self.original_paper = create_paper(title="Original Paper")

        # Create version 1 (first version)
        self.version_1_paper = create_paper(title="Paper Version 1")
        self.version_1 = PaperVersion.objects.create(
            paper=self.version_1_paper,
            version=1,
            base_doi="10.1234/test",
            message="First version",
            original_paper=self.original_paper,
            publication_status=PaperVersion.PREPRINT,
        )

        # Create version 2 (second version)
        self.version_2_paper = create_paper(title="Paper Version 2")
        self.version_2 = PaperVersion.objects.create(
            paper=self.version_2_paper,
            version=2,
            base_doi="10.1234/test",
            message="Second version",
            original_paper=self.original_paper,
            publication_status=PaperVersion.PUBLISHED,
        )

    def test_get_all_paper_versions_with_original_paper_id(self):
        """Test getting all versions when providing the original paper ID."""
        service = PaperService()
        result = service.get_all_paper_versions(self.original_paper.id)

        # Should return all papers: original + versions
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {
            self.original_paper.id,
            self.version_1_paper.id,
            self.version_2_paper.id,
        }

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 3)

    def test_get_all_paper_versions_with_version_paper_id(self):
        """Test getting all versions when providing a version paper ID."""
        result = PaperService().get_all_paper_versions(self.version_1_paper.id)

        # Should return all papers: original + versions
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {
            self.original_paper.id,
            self.version_1_paper.id,
            self.version_2_paper.id,
        }

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 3)

    def test_get_all_paper_versions_with_another_version_paper_id(self):
        """Test getting all versions when providing another version paper ID."""
        result = PaperService().get_all_paper_versions(self.version_2_paper.id)

        # Should return all papers: original + versions
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {
            self.original_paper.id,
            self.version_1_paper.id,
            self.version_2_paper.id,
        }

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 3)

    def test_get_all_paper_versions_single_paper_no_versions(self):
        """Test getting versions for a paper that has no versions."""
        standalone_paper = create_paper(title="Standalone Paper")

        result = PaperService().get_all_paper_versions(standalone_paper.id)

        # Should return only the standalone paper
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {standalone_paper.id}

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 1)

    def test_get_all_paper_versions_nonexistent_paper(self):
        """Test getting versions for a paper that doesn't exist."""
        nonexistent_id = 99999

        result = PaperService().get_all_paper_versions(nonexistent_id)

        # Should return empty queryset
        self.assertEqual(result.count(), 0)
        self.assertFalse(result.exists())

    def test_get_all_paper_versions_removes_duplicates(self):
        """Test that the service removes duplicate paper IDs."""
        # This test ensures the set() operation works correctly
        result = PaperService().get_all_paper_versions(self.original_paper.id)

        # Convert to list to check for duplicates
        paper_ids = list(result.values_list("id", flat=True))
        unique_paper_ids = list(set(paper_ids))

        # Should have no duplicates
        self.assertEqual(len(paper_ids), len(unique_paper_ids))

    def test_get_all_paper_versions_with_complex_chain(self):
        """Test with a more complex version chain."""
        # Create version 3
        version_3_paper = create_paper(title="Paper Version 3")
        PaperVersion.objects.create(
            paper=version_3_paper,
            version=3,
            base_doi="10.1234/test",
            message="Third version",
            original_paper=self.original_paper,
            publication_status=PaperVersion.PREPRINT,
        )

        result = PaperService().get_all_paper_versions(self.original_paper.id)

        # Should return all papers: original + 3 versions
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {
            self.original_paper.id,
            self.version_1_paper.id,
            self.version_2_paper.id,
            version_3_paper.id,
        }

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 4)

    def test_get_all_paper_versions_original_paper_without_version_record(self):
        """Test original paper that doesn't have a PaperVersion record itself."""
        # Create a new original paper without a PaperVersion record
        original_only = create_paper(title="Original Only Paper")

        # Create a version that references this original
        version_paper = create_paper(title="Version of Original Only")
        PaperVersion.objects.create(
            paper=version_paper,
            version=1,
            base_doi="10.5678/test",
            message="Version of original only",
            original_paper=original_only,
            publication_status=PaperVersion.PREPRINT,
        )

        result = PaperService().get_all_paper_versions(original_only.id)

        # Should return both papers
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {original_only.id, version_paper.id}

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 2)


class PaperServiceTests(TestCase):
    """Test the new instance-based PaperService with dependency injection."""

    def setUp(self):
        """Set up test data for paper service tests."""
        # Create original paper
        self.original_paper = create_paper(title="Original Paper")

        # Create version 1
        self.version_1_paper = create_paper(title="Paper Version 1")
        self.version_1 = PaperVersion.objects.create(
            paper=self.version_1_paper,
            version=1,
            base_doi="10.1234/test",
            message="First version",
            original_paper=self.original_paper,
            publication_status=PaperVersion.PREPRINT,
        )

    def test_paper_service_instance_based(self):
        """Test that PaperService works as an instance-based service."""
        service = PaperService()
        result = service.get_all_paper_versions(self.original_paper.id)

        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {self.original_paper.id, self.version_1_paper.id}

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 2)

    def test_paper_service_with_mock_dependencies(self):
        """Test PaperService with mocked dependencies for better testability."""
        # Create mock models
        mock_paper_model = Mock()
        mock_version_model = Mock()

        # Mock a paper instance
        mock_paper = Mock()
        mock_paper.id = 123
        mock_paper_model.objects.get.return_value = mock_paper

        # Mock a paper version instance
        mock_version = Mock()
        mock_version.original_paper.id = 456
        mock_version.paper_id = 789
        mock_version_model.objects.get.return_value = mock_version
        mock_version_model.objects.filter.return_value = [mock_version]

        # Mock the final queryset
        mock_queryset = Mock()
        mock_paper_model.objects.filter.return_value = mock_queryset

        # Create service with mocked dependencies
        service = PaperService(
            paper_model=mock_paper_model, paper_version_model=mock_version_model
        )

        # Test the method
        result = service.get_all_paper_versions(123)

        # Verify the mocks were called correctly
        mock_paper_model.objects.get.assert_called_once_with(id=123)
        mock_version_model.objects.get.assert_called_once_with(paper=mock_paper)
        mock_version_model.objects.filter.assert_called_once_with(original_paper_id=456)
        mock_paper_model.objects.filter.assert_called_once_with(id__in={456, 789})

        # Result should be the mocked queryset
        self.assertEqual(result, mock_queryset)

    def test_get_original_paper(self):
        """Test the get_original_paper method."""
        service = PaperService()

        # Test with version paper - should return original
        original = service.get_original_paper(self.version_1_paper.id)
        self.assertEqual(original, self.original_paper)

        # Test with original paper - should return itself
        original = service.get_original_paper(self.original_paper.id)
        self.assertEqual(original, self.original_paper)

        # Test with nonexistent paper
        original = service.get_original_paper(99999)
        self.assertIsNone(original)

    def test_is_paper_version(self):
        """Test the is_paper_version method."""
        service = PaperService()

        # Version paper should return True
        self.assertTrue(service.is_paper_version(self.version_1_paper.id))

        # Original paper should return False
        self.assertFalse(service.is_paper_version(self.original_paper.id))

        # Nonexistent paper should return False
        self.assertFalse(service.is_paper_version(99999))
