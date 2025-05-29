from django.test import TestCase

from paper.related_models.paper_version import PaperVersion
from paper.services.paper_version_service import PaperVersionService
from paper.tests.helpers import create_paper


class PaperVersionServiceTests(TestCase):
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
        result = PaperVersionService.get_all_paper_versions(self.original_paper.id)

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
        result = PaperVersionService.get_all_paper_versions(self.version_1_paper.id)

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
        result = PaperVersionService.get_all_paper_versions(self.version_2_paper.id)

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

        result = PaperVersionService.get_all_paper_versions(standalone_paper.id)

        # Should return only the standalone paper
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {standalone_paper.id}

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 1)

    def test_get_all_paper_versions_nonexistent_paper(self):
        """Test getting versions for a paper that doesn't exist."""
        nonexistent_id = 99999

        result = PaperVersionService.get_all_paper_versions(nonexistent_id)

        # Should return empty queryset
        self.assertEqual(result.count(), 0)
        self.assertFalse(result.exists())

    def test_get_all_paper_versions_removes_duplicates(self):
        """Test that the service removes duplicate paper IDs."""
        # This test ensures the set() operation works correctly
        result = PaperVersionService.get_all_paper_versions(self.original_paper.id)

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

        result = PaperVersionService.get_all_paper_versions(self.original_paper.id)

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

        result = PaperVersionService.get_all_paper_versions(original_only.id)

        # Should return both papers
        paper_ids = set(result.values_list("id", flat=True))
        expected_ids = {original_only.id, version_paper.id}

        self.assertEqual(paper_ids, expected_ids)
        self.assertEqual(result.count(), 2)
