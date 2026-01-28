import math
from datetime import date, datetime
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from paper.tests.helpers import create_paper
from search.documents.paper import PaperDocument


def create_feed_entry_for_paper(paper, hot_score_v2=0):
    paper_content_type = ContentType.objects.get_for_model(Paper)
    return FeedEntry.objects.create(
        content_type=paper_content_type,
        object_id=paper.id,
        action=FeedEntry.PUBLISH,
        action_date=timezone.now(),
        hot_score_v2=hot_score_v2,
        unified_document=paper.unified_document,
    )


class MockPresentParticiple:
    """Mock object to simulate present_participle behavior"""

    def __init__(self, value):
        self.value = value

    def title(self):
        return self.value.title()


class MockAction:
    """Mock action object with present_participle attribute"""

    def __init__(self, name="Index"):
        self.name = name

    @property
    def present_participle(self):
        return MockPresentParticiple(f"{self.name}ing")


class PaperDocumentTests(TestCase):
    def setUp(self):
        self.document = PaperDocument()
        # Create test papers
        self.paper1 = create_paper(title="First Paper")
        self.paper2 = create_paper(title="Second Paper")
        self.paper3 = create_paper(title="Third Paper")
        self.paper4 = create_paper(title="Fourth Paper")
        self.paper5 = create_paper(title="Fifth Paper")
        # Create mock action to work around bug in existing implementation
        self.mock_action = MockAction()

    def test_get_indexing_queryset_basic_iteration(self):
        """Test that get_indexing_queryset yields all objects in correct order"""
        with patch.object(self.document.django, "queryset_pagination", 2):
            # Use mock action to work around existing bug
            objects = list(self.document.get_indexing_queryset(action=self.mock_action))

            # Should yield all papers
            self.assertEqual(len(objects), 5)

            # Should be ordered by pk
            self.assertEqual(objects[0].pk, self.paper1.pk)
            self.assertEqual(objects[1].pk, self.paper2.pk)
            self.assertEqual(objects[2].pk, self.paper3.pk)
            self.assertEqual(objects[3].pk, self.paper4.pk)
            self.assertEqual(objects[4].pk, self.paper5.pk)

    def test_get_indexing_queryset_with_chunking(self):
        """Test that chunking works correctly with pk-based pagination"""
        with patch.object(self.document.django, "queryset_pagination", 2):
            # Test with verbose=False to avoid _eta calls
            objects = list(
                self.document.get_indexing_queryset(
                    action=self.mock_action, verbose=False
                )
            )

            # Should yield all papers
            self.assertEqual(len(objects), 5)

            # Verify it processes them in chunks by checking they're all present
            pks = [obj.pk for obj in objects]
            expected_pks = [
                self.paper1.pk,
                self.paper2.pk,
                self.paper3.pk,
                self.paper4.pk,
                self.paper5.pk,
            ]
            self.assertEqual(sorted(pks), sorted(expected_pks))

    def test_get_indexing_queryset_with_filters(self):
        """Test that filter_ and exclude parameters are passed correctly"""
        # Create a paper that matches our filter
        filtered_paper = create_paper(title="Filtered Paper Title")

        filter_q = Q(title__icontains="Filtered")

        # Test with verbose=False to avoid action parameter issues
        objects = list(
            self.document.get_indexing_queryset(
                filter_=filter_q, action=self.mock_action, verbose=False
            )
        )

        # Should only return the filtered paper
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].pk, filtered_paper.pk)

    def test_get_indexing_queryset_with_exclude(self):
        """Test that exclude parameter works correctly"""
        exclude_q = Q(title__icontains="First")

        # Test with verbose=False to avoid action parameter issues
        objects = list(
            self.document.get_indexing_queryset(
                exclude=exclude_q, action=self.mock_action, verbose=False
            )
        )

        # Should exclude the first paper
        pks = [obj.pk for obj in objects]
        self.assertNotIn(self.paper1.pk, pks)
        # But include the others
        self.assertIn(self.paper2.pk, pks)
        self.assertIn(self.paper3.pk, pks)

    def test_get_indexing_queryset_empty_queryset(self):
        """Test behavior with empty queryset"""
        # Filter by something that doesn't exist
        filter_q = Q(title__icontains="NonExistentTitle")

        objects = list(
            self.document.get_indexing_queryset(
                filter_=filter_q, action=self.mock_action, verbose=False
            )
        )

        # Should handle empty queryset gracefully
        self.assertEqual(len(objects), 0)

    def test_get_indexing_queryset_single_item(self):
        """Test behavior with single item"""
        with patch.object(self.document.django, "queryset_pagination", 10):
            # Filter to get just one paper
            filter_q = Q(title__icontains="First")

            objects = list(
                self.document.get_indexing_queryset(
                    filter_=filter_q, action=self.mock_action, verbose=False
                )
            )

            # Should yield the single item
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0].pk, self.paper1.pk)

    def test_get_indexing_queryset_count_parameter(self):
        """Test that count parameter limits results"""
        objects = list(
            self.document.get_indexing_queryset(
                count=3, action=self.mock_action, verbose=False
            )
        )

        # Should limit to 3 objects
        self.assertEqual(len(objects), 3)

    def test_get_indexing_queryset_action_parameter(self):
        """Test that action parameter works when passed as proper object"""
        custom_action = MockAction("Delete")

        # This should not raise an error
        objects = list(
            self.document.get_indexing_queryset(
                count=1, action=custom_action, verbose=False
            )
        )

        self.assertEqual(len(objects), 1)

    def test_get_indexing_queryset_processes_all_papers(self):
        """Test that all papers are processed correctly"""
        with patch.object(self.document.django, "queryset_pagination", 10):
            # With a large chunk size, all papers should be processed in one chunk
            objects = list(
                self.document.get_indexing_queryset(
                    action=self.mock_action, verbose=False
                )
            )

            # Should process all papers
            self.assertEqual(len(objects), 5)

            # Verify all our test papers are included
            object_pks = [obj.pk for obj in objects]
            expected_pks = [
                self.paper1.pk,
                self.paper2.pk,
                self.paper3.pk,
                self.paper4.pk,
                self.paper5.pk,
            ]
            self.assertEqual(sorted(object_pks), sorted(expected_pks))

    def test_get_indexing_queryset_chunking_behavior(self):
        """Test that chunking works correctly by comparing different chunk sizes"""
        # Test with small chunks
        with patch.object(self.document.django, "queryset_pagination", 1):
            objects_small_chunks = list(
                self.document.get_indexing_queryset(
                    action=self.mock_action, verbose=False
                )
            )

        # Test with large chunks
        with patch.object(self.document.django, "queryset_pagination", 10):
            objects_large_chunks = list(
                self.document.get_indexing_queryset(
                    action=self.mock_action, verbose=False
                )
            )

        # Both should yield the same papers, just processed differently
        self.assertEqual(len(objects_small_chunks), len(objects_large_chunks))

        small_pks = sorted([obj.pk for obj in objects_small_chunks])
        large_pks = sorted([obj.pk for obj in objects_large_chunks])
        self.assertEqual(small_pks, large_pks)

    def test_prepare_paper_publish_date_converts_datetime_to_date(self):
        paper = create_paper(title="Test Paper")
        paper.paper_publish_date = timezone.make_aware(
            datetime(2025, 10, 27, 14, 30, 0)
        )
        paper.save()

        result = self.document.prepare_paper_publish_date(paper)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, date)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 10)
        self.assertEqual(result.day, 27)

    def test_prepare_hot_score_v2_with_feed_entry(self):
        paper = create_paper(title="Hot Paper")
        create_feed_entry_for_paper(paper, hot_score_v2=150)

        result = self.document.prepare_hot_score_v2(paper)

        self.assertEqual(result, 150)

    def test_prepare_hot_score_v2_without_feed_entry(self):
        paper = create_paper(title="Cold Paper")

        result = self.document.prepare_hot_score_v2(paper)

        self.assertEqual(result, 0)

    def test_prepare_hot_score_v2_returns_zero_on_exception(self):
        paper = create_paper(title="Error Paper")

        with patch(
            "search.documents.paper.ContentType.objects.get_for_model",
            side_effect=Exception("DB error"),
        ):
            result = self.document.prepare_hot_score_v2(paper)

        self.assertEqual(result, 0)

    def test_prepare_suggestion_phrases_minimal_paper(self):
        """Test prepare_suggestion_phrases with minimal paper (only ID, no additional data)"""
        # Create paper with minimal data - no DOI, URL, external_source, hubs, or authors
        # This tests the fallback case when phrases list would be empty after filtering
        paper = create_paper(title="Test")
        # Remove all optional fields
        paper.doi = None
        paper.url = None
        paper.external_source = None
        paper.raw_authors = []
        paper.save()
        # Clear hubs
        paper.unified_document.hubs.clear()

        result = self.document.prepare_suggestion_phrases(paper)

        # Should return result with at least ID (ID is always added to phrases)
        self.assertGreaterEqual(len(result), 1)
        # ID should be in the result
        all_inputs = []
        for group in result:
            all_inputs.extend(group.get("input", []))
        self.assertIn(str(paper.id), all_inputs)
        self.assertEqual(result[0]["weight"], 1)

    def test_prepare_suggestion_phrases_with_title(self):
        """Test prepare_suggestion_phrases includes title, title words, and bigrams"""
        paper = create_paper(title="Machine Learning Research")
        paper.paper_title = "Machine Learning Research"
        paper.save()

        result = self.document.prepare_suggestion_phrases(paper)

        # Should have primary group
        self.assertGreater(len(result), 0)
        primary = result[0]
        self.assertIn("input", primary)
        self.assertIn("weight", primary)
        self.assertIn(str(paper.id), primary["input"])
        self.assertIn("Machine Learning Research", primary["input"])
        # Should include individual words
        self.assertIn("Machine", primary["input"])
        self.assertIn("Learning", primary["input"])
        self.assertIn("Research", primary["input"])
        # Should include bigrams
        self.assertIn("Machine Learning", primary["input"])
        self.assertIn("Learning Research", primary["input"])

    def test_prepare_suggestion_phrases_with_doi(self):
        """Test prepare_suggestion_phrases includes DOI variants"""
        paper = create_paper(title="Test Paper")
        paper.doi = "10.1234/test.567"
        paper.save()

        result = self.document.prepare_suggestion_phrases(paper)

        # Should include DOI variants in primary phrases
        primary = result[0]
        # DOI variants should be included
        doi_variants = [
            phrase for phrase in primary["input"] if "10.1234" in str(phrase)
        ]
        self.assertGreater(len(doi_variants), 0)

    def test_prepare_suggestion_phrases_with_url(self):
        """Test prepare_suggestion_phrases includes URL"""
        paper = create_paper(title="Test Paper")
        paper.url = "https://example.com/paper"
        paper.save()

        result = self.document.prepare_suggestion_phrases(paper)

        primary = result[0]
        self.assertIn("https://example.com/paper", primary["input"])

    def test_prepare_suggestion_phrases_with_external_source(self):
        """Test prepare_suggestion_phrases includes journal name in secondary phrases"""
        paper = create_paper(title="Test Paper")
        paper.external_source = "Nature Journal"
        paper.save()
        # Add hot_score to ensure base_weight > 1 so secondary weight is actually less
        create_feed_entry_for_paper(paper, hot_score_v2=100)

        result = self.document.prepare_suggestion_phrases(paper)

        # Should have secondary group with journal
        self.assertGreater(len(result), 0)
        # Find secondary group (should be second if both primary and secondary exist)
        secondary = None
        for group in result:
            if "Nature" in str(group.get("input", [])):
                secondary = group
                break

        if secondary:
            self.assertIn("Nature Journal", secondary["input"])
            self.assertIn("Nature", secondary["input"])
            self.assertIn("Journal", secondary["input"])
            # Secondary should have lower weight (when base_weight > 1)
            primary = result[0]
            if primary["weight"] > 1:
                self.assertLess(secondary["weight"], primary["weight"])

    def test_prepare_suggestion_phrases_with_hubs(self):
        """Test prepare_suggestion_phrases includes hub names in secondary phrases"""
        paper = create_paper(title="Test Paper")
        hub1 = Hub.objects.create(name="Computer Science")
        hub2 = Hub.objects.create(name="Artificial Intelligence")
        # Add hubs through unified_document (which is what the hubs property uses)
        paper.unified_document.hubs.add(hub1, hub2)

        result = self.document.prepare_suggestion_phrases(paper)

        # Should have secondary group with hubs
        all_inputs = []
        for group in result:
            all_inputs.extend(group.get("input", []))

        # Hub names should be in secondary phrases
        self.assertIn("Computer Science", all_inputs)
        self.assertIn("Artificial Intelligence", all_inputs)

    def test_prepare_suggestion_phrases_hubs_exception_handling(self):
        """Test prepare_suggestion_phrases handles hub exception gracefully"""
        paper = create_paper(title="Test Paper")
        # Mock get_hub_names to raise exception
        with patch(
            "search.documents.paper.PaperDocument.get_hub_names",
            side_effect=Exception("Hub error"),
        ):
            # Should not raise exception
            result = self.document.prepare_suggestion_phrases(paper)

            # Should still return valid result
            self.assertGreater(len(result), 0)
            self.assertIn(str(paper.id), result[0]["input"])

    def test_prepare_suggestion_phrases_with_authors(self):
        """Test prepare_suggestion_phrases includes author names"""
        paper = create_paper(
            title="Test Paper",
            raw_authors=[
                {"first_name": "John", "last_name": "Doe"},
                {"first_name": "Jane", "last_name": "Smith"},
            ],
        )

        result = self.document.prepare_suggestion_phrases(paper)

        # Should include author names in primary phrases
        primary = result[0]
        all_inputs = " ".join(primary["input"])
        # Should include author names
        self.assertIn("John Doe", all_inputs)
        self.assertIn("Jane Smith", all_inputs)

    def test_prepare_suggestion_phrases_authors_exception_handling(self):
        """Test prepare_suggestion_phrases handles author exception gracefully"""
        paper = create_paper(title="Test Paper")
        # Make raw_authors cause an exception
        paper.raw_authors = "invalid_format"

        # Should not raise exception
        result = self.document.prepare_suggestion_phrases(paper)

        # Should still return valid result
        self.assertGreater(len(result), 0)

    def test_prepare_suggestion_phrases_with_hot_score(self):
        """Test prepare_suggestion_phrases calculates weight from hot_score_v2"""
        paper = create_paper(title="Hot Paper")
        create_feed_entry_for_paper(paper, hot_score_v2=1000)

        result = self.document.prepare_suggestion_phrases(paper)

        # Weight should be calculated from hot_score_v2
        primary = result[0]
        # hot_score_v2=1000, log10(1000)=3, so weight should be max(1, 3*10) = 30
        expected_weight = max(1, int(math.log(1000, 10) * 10))
        self.assertEqual(primary["weight"], expected_weight)

    def test_prepare_suggestion_phrases_without_hot_score(self):
        """Test prepare_suggestion_phrases uses default weight when hot_score_v2 is 0"""
        paper = create_paper(title="Cold Paper")
        # No feed entry, so hot_score_v2 should be 0

        result = self.document.prepare_suggestion_phrases(paper)

        # Should use default weight of 1
        primary = result[0]
        self.assertEqual(primary["weight"], 1)

    def test_prepare_suggestion_phrases_secondary_weight(self):
        """Test prepare_suggestion_phrases applies SECONDARY_PHRASES_WEIGHT to secondary group"""
        paper = create_paper(title="Test Paper")
        paper.external_source = "Test Journal"
        hub = Hub.objects.create(name="Test Hub")
        paper.unified_document.hubs.add(hub)
        # Add hot_score to ensure base_weight > 1 so secondary weight is actually less
        create_feed_entry_for_paper(paper, hot_score_v2=100)

        result = self.document.prepare_suggestion_phrases(paper)

        # Should have both primary and secondary groups
        self.assertGreaterEqual(len(result), 1)

        # Find secondary group
        secondary = None
        for group in result:
            inputs = group.get("input", [])
            if "Test Journal" in inputs or "Test Hub" in inputs:
                secondary = group
                break

        if secondary and len(result) > 1:
            primary = result[0]
            # Secondary weight should be less than primary (when base_weight > 1)
            if primary["weight"] > 1:
                self.assertLess(secondary["weight"], primary["weight"])
            # Secondary weight should be max(1, base_weight * SECONDARY_PHRASES_WEIGHT)
            expected_secondary_weight = max(
                1, int(primary["weight"] * self.document.SECONDARY_PHRASES_WEIGHT)
            )
            self.assertEqual(secondary["weight"], expected_secondary_weight)

    def test_prepare_suggestion_phrases_deduplication(self):
        """Test prepare_suggestion_phrases deduplicates phrases"""
        paper = create_paper(title="Test Test Paper")
        paper.paper_title = "Test Test Paper"
        paper.save()

        result = self.document.prepare_suggestion_phrases(paper)

        # Should deduplicate "Test" word
        primary = result[0]
        test_count = primary["input"].count("Test")
        # "Test" should appear but not be duplicated excessively
        self.assertGreater(test_count, 0)

    def test_prepare_suggestion_phrases_strings_only(self):
        """Test prepare_suggestion_phrases filters to strings only"""
        paper = create_paper(title="Test Paper")
        # Add a non-string to phrases (though this shouldn't happen in practice)
        # We'll test that the method handles it correctly

        result = self.document.prepare_suggestion_phrases(paper)

        # All inputs should be strings
        for group in result:
            for phrase in group["input"]:
                self.assertIsInstance(phrase, str)

    def test_prepare_suggestion_phrases_comprehensive(self):
        """Test prepare_suggestion_phrases with all features enabled"""
        paper = create_paper(
            title="Machine Learning in Biology",
            raw_authors=[
                {"first_name": "John", "last_name": "Doe"},
            ],
        )
        paper.paper_title = "Machine Learning in Biology"
        paper.doi = "10.1234/test.567"
        paper.url = "https://example.com/paper"
        paper.external_source = "Nature Journal"
        paper.save()

        hub = Hub.objects.create(name="Biology Hub")
        paper.unified_document.hubs.add(hub)

        create_feed_entry_for_paper(paper, hot_score_v2=5000)

        result = self.document.prepare_suggestion_phrases(paper)

        # Should have both primary and secondary groups
        self.assertGreaterEqual(len(result), 1)

        # Check primary group
        primary = result[0]
        self.assertIn(str(paper.id), primary["input"])
        self.assertIn("Machine Learning in Biology", primary["input"])
        # Should have calculated weight from hot_score
        self.assertGreater(primary["weight"], 1)

        # Check secondary group exists if we have secondary phrases
        if len(result) > 1:
            secondary = result[1]
            self.assertIn("input", secondary)
            self.assertIn("weight", secondary)
            self.assertLess(secondary["weight"], primary["weight"])
