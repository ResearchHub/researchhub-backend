from unittest.mock import Mock

from django.test import TestCase

from paper.ingestion.mappers.enrichment.openalex import OpenAlexMapper
from paper.ingestion.services.openalex_enrichment import PaperOpenAlexEnrichmentService
from paper.models import Paper
from user.related_models.author_model import Author
from user.tests.helpers import create_random_default_user


class ProcessAuthorsDuplicateTests(TestCase):
    """Tests for process_authors handling of duplicate openalex_ids."""

    def setUp(self):
        self.user = create_random_default_user("enrichmentTest")
        self.paper = Paper.objects.create(
            title="Test Paper",
            doi="10.1234/test",
            uploaded_by=self.user,
        )
        self.mapper = OpenAlexMapper()
        self.service = PaperOpenAlexEnrichmentService(
            openalex_client=Mock(), openalex_mapper=self.mapper
        )

    def test_process_authors_handles_duplicate_openalex_ids(self):
        """
        Regression test for RESEARCHHUB-BACKEND-4KQ0:
        When multiple Author records share the same openalex_ids,
        update_or_create raises MultipleObjectsReturned.
        The fix uses filter().first() to pick one and update it.
        """
        openalex_ids = ["A123456"]

        Author.objects.create(
            first_name="John",
            last_name="Doe",
            openalex_ids=openalex_ids,
            created_source=Author.SOURCE_OPENALEX,
        )
        Author.objects.create(
            first_name="John",
            last_name="Doe",
            openalex_ids=openalex_ids,
            created_source=Author.SOURCE_OPENALEX,
        )

        self.assertEqual(Author.objects.filter(openalex_ids=openalex_ids).count(), 2)

        openalex_data = {
            "raw_data": {
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A123456",
                            "display_name": "John Doe Updated",
                            "orcid": "https://orcid.org/0000-0001-2345-6789",
                        },
                        "author_position": "first",
                        "raw_author_name": "John Doe Updated",
                    }
                ]
            }
        }

        created, updated = self.service.process_authors(self.paper, openalex_data)

        self.assertEqual(updated, 1)
        self.assertEqual(created, 0)

    def test_process_authors_creates_new_author(self):
        """Normal case: new author gets created."""
        openalex_data = {
            "raw_data": {
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A999999",
                            "display_name": "Jane New",
                            "orcid": "https://orcid.org/0000-0009-8765-4321",
                        },
                        "author_position": "first",
                        "raw_author_name": "Jane New",
                    }
                ]
            }
        }

        created, updated = self.service.process_authors(self.paper, openalex_data)

        self.assertEqual(created, 1)
        self.assertEqual(updated, 0)
        self.assertTrue(Author.objects.filter(openalex_ids=["A999999"]).exists())

    def test_process_authors_updates_existing_author(self):
        """Existing single author gets updated."""
        Author.objects.create(
            first_name="Old",
            last_name="Name",
            openalex_ids=["A555555"],
            created_source=Author.SOURCE_OPENALEX,
        )

        openalex_data = {
            "raw_data": {
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A555555",
                            "display_name": "New Name",
                            "orcid": "https://orcid.org/0000-0005-5555-5555",
                        },
                        "author_position": "first",
                        "raw_author_name": "New Name",
                    }
                ]
            }
        }

        created, updated = self.service.process_authors(self.paper, openalex_data)

        self.assertEqual(created, 0)
        self.assertEqual(updated, 1)
        author = Author.objects.filter(openalex_ids=["A555555"]).first()
        self.assertEqual(author.first_name, "New")
        self.assertEqual(author.last_name, "Name")
