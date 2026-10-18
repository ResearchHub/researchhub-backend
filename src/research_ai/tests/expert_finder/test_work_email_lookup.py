"""Unit tests for scholarly metadata email lookup."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.expert_finder.work_email_lookup import (
    bind_emails_to_authors,
    emails_from_openalex_authorships,
    emails_in_text,
    lookup_work_emails,
    lookup_work_emails_for_page,
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
                "raw_affiliation_strings": ["MIT; email: ada.expert@mit.edu"],
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

    def test_bind_emails_rejects_sole_hit_named_for_other_coauthor(self):
        # Arrange: sole Europe PMC hit names Bob; Ada is the only correspondent.
        # Bob may be absent from the bound author cards (e.g. trimmed middle).
        authors = [
            {
                "openalex_author_id": "A1",
                "display_name": "Ada Expert",
                "is_corresponding": True,
            },
        ]
        hits = [
            {
                "email": "bob@ox.ac.uk",
                "display_name": "Bob Other",
                "source": "europe_pmc",
                "is_corresponding": False,
            }
        ]

        # Act
        bound = bind_emails_to_authors(authors, hits)

        # Assert: do not attach Bob's address to corresponding Ada.
        self.assertNotIn("metadata_email", bound[0])

    def test_bind_emails_allows_anonymous_sole_hit_for_correspondent(self):
        # Arrange: sole hit has no identity; one corresponding author.
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
                "email": "corr@mit.edu",
                "display_name": None,
                "source": "crossref",
                "is_corresponding": False,
            }
        ]

        # Act
        bound = bind_emails_to_authors(authors, hits)

        # Assert
        self.assertEqual(bound[0]["metadata_email"], "corr@mit.edu")
        self.assertNotIn("metadata_email", bound[1])

    def test_bind_emails_skips_ambiguous_shared_surname(self):
        # Arrange: coauthors share a surname; hit lacks id / exact full name.
        authors = [
            {
                "openalex_author_id": "A1",
                "display_name": "Ada Smith",
                "is_corresponding": False,
            },
            {
                "openalex_author_id": "A2",
                "display_name": "Bob Smith",
                "is_corresponding": False,
            },
        ]
        hits = [
            {
                "email": "a.smith@univ.edu",
                "display_name": "A Smith",
                "source": "europe_pmc",
                "is_corresponding": False,
            }
        ]

        # Act
        bound = bind_emails_to_authors(authors, hits)

        # Assert: do not assign by surname alone to either Smith.
        self.assertNotIn("metadata_email", bound[0])
        self.assertNotIn("metadata_email", bound[1])

    def test_bind_emails_matches_unique_full_name_without_author_id(self):
        # Arrange
        authors = [
            {
                "openalex_author_id": "A1",
                "display_name": "Ada Expert",
                "is_corresponding": False,
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
                "source": "crossref",
                "is_corresponding": False,
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

    def test_lookup_for_page_uses_openalex_without_remote(self):
        # Arrange
        authorships_a = [
            {
                "author": {
                    "id": "https://openalex.org/A1",
                    "display_name": "Ada Expert",
                },
                "raw_affiliation_strings": ["MIT; ada@mit.edu"],
            }
        ]
        authorships_b = [
            {
                "author": {
                    "id": "https://openalex.org/A2",
                    "display_name": "Bob Other",
                },
                "raw_affiliation_strings": ["Oxford; bob@ox.ac.uk"],
            }
        ]

        # Act
        page = lookup_work_emails_for_page(
            [("10.1/abc", authorships_a), (None, authorships_b)]
        )

        # Assert
        self.assertEqual(page[0][0]["email"], "ada@mit.edu")
        self.assertEqual(page[1][0]["email"], "bob@ox.ac.uk")

    def test_lookup_for_page_calls_injected_fn_per_job(self):
        # Arrange
        seen: list[str | None] = []

        def _lookup(*, doi, authorships):
            seen.append(doi)
            return [{"email": f"{doi}@example.edu", "source": "test"}]

        # Act
        page = lookup_work_emails_for_page(
            [("10.1/a", []), ("10.1/b", [])],
            lookup_fn=_lookup,
        )

        # Assert
        self.assertCountEqual(seen, ["10.1/a", "10.1/b"])
        self.assertEqual(page[0][0]["email"], "10.1/a@example.edu")
        self.assertEqual(page[1][0]["email"], "10.1/b@example.edu")

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
        self.assertEqual(
            emails_in_text("reach me at ada@ox.ac.uk"),
            ["ada@ox.ac.uk"],
        )
