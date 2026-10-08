"""Unit tests for scholarly metadata email lookup."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.expert_finder.work_email_lookup import (
    bind_emails_to_authors,
    emails_from_openalex_authorships,
    emails_in_text,
    lookup_work_emails,
    normalize_doi,
)


class WorkEmailLookupHelpersTests(SimpleTestCase):
    def test_normalize_doi(self):
        # Arrange / Act / Assert
        self.assertEqual(normalize_doi("https://doi.org/10.1/abc"), "10.1/abc")
        self.assertEqual(normalize_doi("DOI:10.1/abc"), "10.1/abc")

    def test_emails_from_openalex_affiliation_strings(self):
        # Arrange
        authorships = [
            {
                "is_corresponding": True,
                "author": {
                    "id": "https://openalex.org/A1",
                    "display_name": "Ada Expert",
                },
                "raw_affiliation_strings": [
                    "MIT; email: ada.expert@mit.edu"
                ],
            }
        ]
        # Act
        hits = emails_from_openalex_authorships(authorships)
        # Assert
        self.assertEqual(hits[0]["email"], "ada.expert@mit.edu")
        self.assertTrue(hits[0]["is_corresponding"])

    def test_bind_emails_prefers_corresponding_single_hit(self):
        # Arrange
        authors = [
            {
                "openalex_author_id": "A1",
                "display_name": "Ada Expert",
                "is_corresponding": True,
            },
            {
                "openalex_author_id": "A2",
                "display_name": "Bob Other",
                "is_corresponding": False,
            },
        ]
        hits = [
            {
                "email": "ada@mit.edu",
                "display_name": "Ada Expert",
                "source": "europe_pmc",
                "is_corresponding": True,
            }
        ]
        # Act
        bound = bind_emails_to_authors(authors, hits)
        # Assert
        self.assertEqual(bound[0]["metadata_email"], "ada@mit.edu")
        self.assertNotIn("metadata_email", bound[1])

    def test_lookup_skips_remote_when_openalex_has_email(self):
        # Arrange
        session = MagicMock()
        authorships = [
            {
                "author": {
                    "id": "https://openalex.org/A1",
                    "display_name": "Ada Expert",
                },
                "raw_affiliation_strings": ["MIT; ada@mit.edu"],
            }
        ]

        # Act
        hits = lookup_work_emails(
            doi="10.1/abc", authorships=authorships, session=session
        )

        # Assert
        self.assertEqual([h["email"] for h in hits], ["ada@mit.edu"])
        session.get.assert_not_called()

    def test_lookup_falls_back_to_europe_pmc_when_openalex_empty(self):
        # Arrange
        session = MagicMock()
        epmc = MagicMock()
        epmc.status_code = 200
        epmc.json.return_value = {
            "resultList": {
                "result": [
                    {
                        "authorList": {
                            "author": [
                                {
                                    "fullName": "Ada Expert",
                                    "affiliation": "Dept; ada@ox.ac.uk",
                                }
                            ]
                        }
                    }
                ]
            }
        }
        session.get.return_value = epmc

        # Act
        hits = lookup_work_emails(doi="10.1/abc", authorships=[], session=session)
        emails = {h["email"] for h in hits}

        # Assert
        self.assertEqual(emails, {"ada@ox.ac.uk"})
        self.assertEqual(session.get.call_count, 1)
        self.assertTrue(emails_in_text("reach me at a@b.com"))
