from django.test import TestCase

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT, PAPER


class RfpFeedExclusionTests(TestCase):
    def create_document(self, *, document_type=GRANT, excluded=True):
        document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type
        )
        document.document_filter.is_excluded_in_feed = excluded
        document.document_filter.save(update_fields=["is_excluded_in_feed"])
        return document

    def test_non_rfp_does_not_query_its_filter(self):
        # Arrange
        document = self.create_document(document_type=PAPER)
        document = ResearchhubUnifiedDocument.objects.get(pk=document.pk)

        # Act / Assert
        with self.assertNumQueries(0):
            self.assertFalse(document.is_rfp_excluded_from_feed)

    def test_cached_rfp_filter_does_not_require_a_query(self):
        # Arrange / Act / Assert
        for excluded in (True, False):
            with self.subTest(excluded=excluded):
                document = self.create_document(excluded=excluded)
                with self.assertNumQueries(0):
                    self.assertEqual(document.is_rfp_excluded_from_feed, excluded)

    def test_preloaded_rfp_filter_does_not_require_a_query(self):
        # Arrange
        document = self.create_document()
        document = ResearchhubUnifiedDocument.objects.select_related(
            "document_filter"
        ).get(pk=document.pk)

        # Act / Assert
        with self.assertNumQueries(0):
            self.assertTrue(document.is_rfp_excluded_from_feed)

    def test_uncached_rfp_uses_one_query(self):
        # Arrange
        document = self.create_document()
        document = ResearchhubUnifiedDocument.objects.get(pk=document.pk)

        # Act / Assert
        with self.assertNumQueries(1):
            self.assertTrue(document.is_rfp_excluded_from_feed)

    def test_missing_filter_does_not_require_a_query(self):
        # Arrange
        document = self.create_document()
        ResearchhubUnifiedDocument.objects.filter(pk=document.pk).update(
            document_filter=None
        )
        document = ResearchhubUnifiedDocument.objects.get(pk=document.pk)

        # Act / Assert
        with self.assertNumQueries(0):
            self.assertFalse(document.is_rfp_excluded_from_feed)
