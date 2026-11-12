"""
Tests for BioRxiv client.
"""

from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

from paper.ingestion.clients.preprints.biorxiv import BioRxivClient, BioRxivConfig


class TestBioRxivClient(TestCase):
    """Test cases for BioRxiv client using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = BioRxivConfig()
        self.client = BioRxivClient(self.config)

        # Sample API response
        self.sample_response = {
            "messages": [
                {
                    "status": "ok",
                    "category": "all",
                    "interval": "2025-01-01:2025-01-01",
                    "funder": "all",
                    "cursor": 0,
                    "count": 2,
                    "count_new_papers": "2",
                    "total": "57",
                }
            ],
            "collection": [
                {
                    "title": "Persistent DNA methylation paper",
                    "authors": "Gomez Cuautle, D. D.; Rossi, A. R.",
                    "author_corresponding": "Alberto Javier Ramos",
                    "author_corresponding_institution": "CONICET",
                    "doi": "10.1101/2024.12.31.630767",
                    "date": "2025-01-01",
                    "version": "1",
                    "type": "new results",
                    "license": "cc_no",
                    "category": "neuroscience",
                    "jatsxml": (
                        "https://www.biorxiv.org/content/early/2025/01/01/"
                        "2024.12.31.630767.source.xml"
                    ),
                    "abstract": "Epilepsy is a debilitating neurological disorder...",
                    "funder": "NA",
                    "published": "NA",
                    "server": "bioRxiv",
                },
                {
                    "title": "YX0798 CDK9 Inhibitor",
                    "authors": "Jiang, V.; Xue, Y.",
                    "author_corresponding": "Vivian Jiang",
                    "author_corresponding_institution": "MD Anderson",
                    "doi": "10.1101/2024.12.31.629756",
                    "date": "2025-01-01",
                    "version": "1",
                    "type": "new results",
                    "license": "cc_no",
                    "category": "cancer biology",
                    "jatsxml": (
                        "https://www.biorxiv.org/content/early/2025/01/01/"
                        "2024.12.31.629756.source.xml"
                    ),
                    "abstract": "Non-genetic transcription evolution...",
                    "funder": "NA",
                    "published": "10.1182/bloodadvances.2025016511",
                    "server": "bioRxiv",
                },
            ],
        }

    def test_parse(self):
        """Test parsing of BioRxiv API response."""
        papers = self.client.parse(self.sample_response)

        self.assertEqual(len(papers), 2)

        # Check first paper
        paper1 = papers[0]
        self.assertEqual(paper1["doi"], "10.1101/2024.12.31.630767")
        self.assertEqual(paper1["version"], "1")
        self.assertEqual(paper1["title"], "Persistent DNA methylation paper")
        self.assertEqual(paper1["category"], "neuroscience")
        self.assertEqual(paper1["server"], "bioRxiv")
        self.assertEqual(paper1["date"], "2025-01-01")
        self.assertEqual(paper1["license"], "cc_no")

        # Check second paper (has published info)
        paper2 = papers[1]
        self.assertEqual(paper2["doi"], "10.1101/2024.12.31.629756")
        self.assertEqual(paper2["published"], "10.1182/bloodadvances.2025016511")
        self.assertEqual(paper2["category"], "cancer biology")

    @patch("requests.Session.get")
    def test_fetch_with_retry(self, mock_get):
        """Test fetch with retry logic."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = self.sample_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.client.fetch_with_retry(
            "/details/biorxiv/2025-01-01/2025-01-01/0/json"
        )

        self.assertEqual(result, self.sample_response)
        mock_get.assert_called_once()

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_fetch_recent(self, mock_fetch):
        """Test fetching recent papers."""
        # Mock response - return empty list after first call to stop pagination
        mock_fetch.side_effect = [
            self.sample_response,
            {"messages": [], "collection": []},
        ]

        # Fetch papers
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 1)
        )

        # Check results
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["doi"], "10.1101/2024.12.31.630767")

        # Verify endpoint was called correctly
        mock_fetch.assert_any_call("/details/biorxiv/2025-01-01/2025-01-01/0/json")
