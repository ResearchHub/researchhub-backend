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

    def test_get_all_paper_versions_nonexistent_paper(self):
        """Test getting versions for a paper that doesn't exist."""
        nonexistent_id = 99999

        result = PaperService().get_all_paper_versions(nonexistent_id)

        # Should return empty queryset
        self.assertEqual(result.count(), 0)
        self.assertFalse(result.exists())

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
