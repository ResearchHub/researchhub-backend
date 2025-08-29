from unittest.mock import patch

from django.db.models import Q
from django.test import TestCase

from paper.tests.helpers import create_paper
from search.documents.paper import PaperDocument


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
