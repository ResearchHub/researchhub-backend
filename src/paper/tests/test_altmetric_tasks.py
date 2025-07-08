from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from paper.altmetric_tasks import (
    enrich_papers_with_altmetric_data,
    enrich_single_paper_with_altmetric,
    extract_relevant_altmetric_fields,
)
from paper.models import Paper
from paper.tests.helpers import create_paper


class TestExtractRelevantAltmetricFields(TestCase):
    def test_extract_relevant_fields_full_data(self):
        """Test extraction with complete Altmetric data."""
        altmetric_data = {
            "score": 217.25,
            "cited_by_posts_count": 105,
            "cited_by_accounts_count": 100,
            "cited_by_msm_count": 15,
            "cited_by_feeds_count": 8,
            "cited_by_patents_count": 13,
            "cited_by_wikipedia_count": 3,
            "cited_by_tweeters_count": 42,
            "cited_by_fbwalls_count": 6,
            "cited_by_gplus_count": 12,
            "cited_by_bluesky_count": 1,
            "readers_count": 936,
            "readers": {
                "mendeley": 1483,
                "citeulike": 4,
                "connotea": 0,
            },
            "context": {
                "all": {
                    "pct": 99,
                    "rank": 201059,
                    "count": 28802336,
                    "higher_than": 28603774,
                },
                "journal": {
                    "pct": 89,
                    "rank": 11411,
                    "count": 105751,
                    "higher_than": 94338,
                },
            },
            "cohorts": {"pub": 34, "sci": 7, "com": 2},
            "history": {
                "1d": 0,
                "1w": 0,
                "1m": 0,
                "3m": 0.25,
                "6m": 3.25,
                "1y": 3.25,
                "at": 217.25,
            },
            # Fields that should be ignored
            "doi": "10.1038/nature12373",
            "title": "Nanometre-scale thermometry in a living cell",
            "abstract": "Long abstract text...",
        }

        result = extract_relevant_altmetric_fields(altmetric_data)

        # Check core metrics are extracted
        self.assertEqual(result["score"], 217.25)
        self.assertEqual(result["cited_by_posts_count"], 105)
        self.assertEqual(result["cited_by_msm_count"], 15)

        # Check readers are extracted
        self.assertEqual(result["readers_count"], 936)
        self.assertEqual(result["readers_mendeley"], 1483)

        # Check context is extracted
        self.assertEqual(result["context_all_pct"], 99)
        self.assertEqual(result["context_all_rank"], 201059)
        self.assertEqual(result["context_journal_pct"], 89)

        # Check cohorts are extracted
        self.assertEqual(result["cohorts_pub"], 34)
        self.assertEqual(result["cohorts_sci"], 7)

        # Check history is extracted
        self.assertEqual(result["history_3m"], 0.25)
        self.assertEqual(result["history_at"], 217.25)

        # Check non-metric fields are not included
        self.assertNotIn("doi", result)
        self.assertNotIn("title", result)
        self.assertNotIn("abstract", result)

    def test_extract_relevant_fields_partial_data(self):
        """Test extraction with partial Altmetric data."""
        altmetric_data = {
            "score": 10.5,
            "cited_by_posts_count": 5,
            "readers": {"mendeley": 50},
            "context": {"all": {"pct": 75}},
        }

        result = extract_relevant_altmetric_fields(altmetric_data)

        self.assertEqual(result["score"], 10.5)
        self.assertEqual(result["cited_by_posts_count"], 5)
        self.assertEqual(result["readers_mendeley"], 50)
        self.assertEqual(result["context_all_pct"], 75)

        # Check None values are not included
        self.assertNotIn("cited_by_msm_count", result)
        self.assertNotIn("readers_citeulike", result)

    def test_extract_relevant_fields_none_input(self):
        """Test extraction with None input."""
        result = extract_relevant_altmetric_fields(None)
        self.assertEqual(result, {})

    def test_extract_relevant_fields_empty_dict(self):
        """Test extraction with empty dictionary."""
        result = extract_relevant_altmetric_fields({})
        self.assertEqual(result, {})


class TestEnrichSinglePaperWithAltmetric(TestCase):
    def setUp(self):
        self.paper = create_paper()
        self.paper.doi = "10.1038/nature12373"
        self.paper.save()

    @patch("paper.altmetric_tasks.Altmetric")
    def test_enrich_single_paper_success(self, mock_altmetric_class):
        """Test successful enrichment of a single paper."""
        mock_altmetric = mock_altmetric_class.return_value
        mock_altmetric.get_altmetric_data.return_value = {
            "score": 100,
            "cited_by_posts_count": 50,
            "readers": {"mendeley": 200},
        }

        result = enrich_single_paper_with_altmetric(self.paper.id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["altmetric_score"], 100)

        # Reload paper and check metadata
        self.paper.refresh_from_db()
        self.assertIsNotNone(self.paper.external_metadata)
        self.assertIn("altmetric", self.paper.external_metadata)
        self.assertIn("altmetric_updated_at", self.paper.external_metadata)
        self.assertEqual(self.paper.external_metadata["altmetric"]["score"], 100)
        self.assertEqual(
            self.paper.external_metadata["altmetric"]["cited_by_posts_count"], 50
        )

    @patch("paper.altmetric_tasks.Altmetric")
    def test_enrich_single_paper_not_found(self, mock_altmetric_class):
        """Test enrichment when Altmetric data is not found."""
        mock_altmetric = mock_altmetric_class.return_value
        mock_altmetric.get_altmetric_data.return_value = None

        result = enrich_single_paper_with_altmetric(self.paper.id)

        self.assertEqual(result["status"], "not_found")

        # Check paper metadata was not modified
        self.paper.refresh_from_db()
        self.assertIsNone(self.paper.external_metadata)

    def test_enrich_single_paper_no_doi(self):
        """Test enrichment when paper has no DOI."""
        self.paper.doi = None
        self.paper.save()

        result = enrich_single_paper_with_altmetric(self.paper.id)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_doi")

    def test_enrich_single_paper_not_exists(self):
        """Test enrichment when paper doesn't exist."""
        result = enrich_single_paper_with_altmetric(999999)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "paper_not_found")

    @patch("paper.altmetric_tasks.Altmetric")
    def test_enrich_single_paper_with_existing_metadata(self, mock_altmetric_class):
        """Test enrichment preserves existing external_metadata."""
        # Set existing metadata
        self.paper.external_metadata = {"existing_key": "existing_value"}
        self.paper.save()

        mock_altmetric = mock_altmetric_class.return_value
        mock_altmetric.get_altmetric_data.return_value = {
            "score": 50,
            "cited_by_posts_count": 25,
        }

        result = enrich_single_paper_with_altmetric(self.paper.id)

        self.assertEqual(result["status"], "success")

        # Check existing metadata is preserved
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.external_metadata["existing_key"], "existing_value")
        self.assertIn("altmetric", self.paper.external_metadata)


class TestEnrichPapersWithAltmetricData(TestCase):
    def setUp(self):
        # Create papers with various states
        self.paper_with_doi = create_paper()
        self.paper_with_doi.doi = "10.1038/nature12373"
        self.paper_with_doi.save()

        self.paper_without_doi = create_paper()
        self.paper_without_doi.doi = None
        self.paper_without_doi.save()

        self.paper_empty_doi = create_paper()
        self.paper_empty_doi.doi = ""
        self.paper_empty_doi.save()

        # Create an old paper (should not be processed)
        self.old_paper = create_paper()
        self.old_paper.doi = "10.1038/old12345"
        self.old_paper.created_date = timezone.now() - timedelta(days=200)
        self.old_paper.save()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.altmetric_tasks.Altmetric")
    def test_enrich_papers_success(self, mock_altmetric_class):
        """Test successful enrichment of multiple papers."""
        mock_altmetric = mock_altmetric_class.return_value
        mock_altmetric.get_altmetric_data.side_effect = [
            {"score": 100, "cited_by_posts_count": 50},  # For paper_with_doi
        ]

        result = enrich_papers_with_altmetric_data.apply().get()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 1)  # Only paper_with_doi
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["not_found_count"], 0)
        self.assertEqual(result["error_count"], 0)

        # Check the paper was enriched
        self.paper_with_doi.refresh_from_db()
        self.assertIsNotNone(self.paper_with_doi.external_metadata)
        self.assertEqual(
            self.paper_with_doi.external_metadata["altmetric"]["score"], 100
        )

        # Check old paper was not processed
        self.old_paper.refresh_from_db()
        self.assertIsNone(self.old_paper.external_metadata)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.altmetric_tasks.Altmetric")
    def test_enrich_papers_mixed_results(self, mock_altmetric_class):
        """Test enrichment with mixed success/not found results."""
        # Create another paper with DOI
        paper2 = create_paper()
        paper2.doi = "10.1038/another12345"
        paper2.save()

        mock_altmetric = mock_altmetric_class.return_value
        mock_altmetric.get_altmetric_data.side_effect = [
            {"score": 100, "cited_by_posts_count": 50},  # First paper found
            None,  # Second paper not found
        ]

        result = enrich_papers_with_altmetric_data.apply().get()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["not_found_count"], 1)
        self.assertEqual(result["error_count"], 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_enrich_papers_no_papers(self):
        """Test enrichment when no papers need processing."""
        # Delete all recent papers
        Paper.objects.filter(
            created_date__gte=timezone.now() - timedelta(days=100)
        ).delete()

        result = enrich_papers_with_altmetric_data.apply().get()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.altmetric_tasks.Altmetric")
    @patch("paper.altmetric_tasks.sentry")
    def test_enrich_papers_with_errors(self, mock_sentry, mock_altmetric_class):
        """Test enrichment handles individual paper errors gracefully."""
        mock_altmetric = mock_altmetric_class.return_value
        mock_altmetric.get_altmetric_data.side_effect = Exception("API Error")

        result = enrich_papers_with_altmetric_data.apply().get()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 1)
        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["not_found_count"], 0)
        self.assertEqual(result["error_count"], 1)

        # Check that sentry was called
        mock_sentry.log_error.assert_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.altmetric_tasks.Altmetric")
    @patch("paper.altmetric_tasks.sentry")
    def test_enrich_papers_fatal_error_with_retry(
        self, mock_sentry, mock_altmetric_class
    ):
        """Test task retry on fatal error."""
        # Mock the entire task to raise an exception
        mock_altmetric_class.side_effect = Exception("Fatal error")

        with self.assertRaises(Exception):
            enrich_papers_with_altmetric_data.apply().get()
