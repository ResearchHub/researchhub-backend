from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


class ModelTests(TestCase):
    """Tests for ResearchhubUnifiedDocument model methods"""

    def setUp(self):
        self.user = create_random_default_user("test_user")
        self.paper = create_paper(uploaded_by=self.user)

    def test_get_journal_returns_none_when_no_journal_hubs(self):
        """Test that get_journal returns None when document has no journal hubs"""
        regular_hub = create_hub("Regular Hub")
        self.paper.unified_document.hubs.add(regular_hub)

        result = self.paper.unified_document.get_journal()

        self.assertIsNone(result)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "999999")
    def test_get_journal_returns_journal_hub(self):
        """Test that get_journal returns a journal hub when one exists"""
        journal_hub = create_hub("Nature", namespace=Hub.Namespace.JOURNAL)
        self.paper.unified_document.hubs.add(journal_hub)

        result = self.paper.unified_document.get_journal()

        self.assertEqual(result, journal_hub)

    def test_get_journal_prioritizes_researchhub_journal(self):
        """Test that get_journal prioritizes ResearchHub Journal over other journals"""
        other_journal = create_hub("Other Journal", namespace=Hub.Namespace.JOURNAL)
        rh_journal = create_hub("ResearchHub Journal", namespace=Hub.Namespace.JOURNAL)
        self.paper.unified_document.hubs.add(other_journal)
        self.paper.unified_document.hubs.add(rh_journal)

        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(rh_journal.id)):
            result = self.paper.unified_document.get_journal()

        self.assertEqual(result, rh_journal)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "999999")
    def test_get_journal_prioritizes_preprint(self):
        """Test that get_journal prioritizes biorxiv preprint server"""
        other_journal = create_hub("Other Journal", namespace=Hub.Namespace.JOURNAL)
        biorxiv = Hub.objects.create(
            name="bioRxiv", slug="biorxiv", namespace=Hub.Namespace.JOURNAL
        )
        self.paper.unified_document.hubs.add(other_journal)
        self.paper.unified_document.hubs.add(biorxiv)

        result = self.paper.unified_document.get_journal()

        self.assertEqual(result, biorxiv)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "999999")
    def test_get_journal_ignores_non_journal_hubs(self):
        """Test that get_journal ignores hubs without JOURNAL namespace"""
        category_hub = create_hub("Category Hub", namespace=Hub.Namespace.CATEGORY)
        journal_hub = create_hub("Science", namespace=Hub.Namespace.JOURNAL)
        self.paper.unified_document.hubs.add(category_hub)
        self.paper.unified_document.hubs.add(journal_hub)

        result = self.paper.unified_document.get_journal()

        self.assertEqual(result, journal_hub)
