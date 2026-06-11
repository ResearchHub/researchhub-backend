"""Unit tests for researcher_profile.builder (assembly + entry points)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from research_ai.models import Expert
from research_ai.services.researcher_profile import builder
from research_ai.tests.researcher_profile.helpers import (
    make_expert,
    oa_author_record,
    oa_work,
)
from utils.openalex import Work


class ClaimsTests(SimpleTestCase):
    def test_every_claim_has_url_and_dedupes(self):
        # Act
        claims = builder._build_claims(
            [
                Work("A Paper", "2021", "https://doi.org/10.1/abc"),
                Work("A Paper", "2021", "https://doi.org/10.1/abc"),  # dup
            ]
        )
        # Assert: every claim has a URL; the duplicate work collapses to one.
        self.assertTrue(all(c["url"] for c in claims))
        texts = [c["text"] for c in claims]
        self.assertEqual(texts.count("(2021) A Paper"), 1)

    def test_work_without_source_url_is_dropped(self):
        # Act: a work with no source URL can't be cited -> dropped.
        claims = builder._build_claims([Work("A Paper", "2021", "")])
        # Assert
        self.assertEqual(claims, [])


class BuildProfileTests(SimpleTestCase):
    def test_builds_full_profile_from_name_match(self):
        # Arrange
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [oa_author_record(orcid=None)]
        }
        client.get_works_typed.return_value = [
            Work.from_openalex(oa_work("Lead Paper", 2024, "first"), author_id="A123")
        ]
        expert = make_expert(affiliation="Stanford University", expertise="genomics")
        # Act
        profile = builder.build_expert_profile(expert, oa_client=client)
        # Assert
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["resolution"]["match_method"], "name+affiliation")
        self.assertEqual(profile["works"][0]["author_position"], "first")
        # Authorship position is surfaced on the work's claim text.
        self.assertIn(
            "(2024) Lead Paper [first author]",
            [c["text"] for c in profile["claims"]],
        )
        self.assertTrue(all(c["url"] for c in profile["claims"]))
        self.assertIn("Selected works", profile["context_text"])
        self.assertEqual(profile["errors"], [])

    def test_unresolved_expert_builds_empty_profile(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        # Act
        profile = builder.build_expert_profile(make_expert(), oa_client=client)
        # Assert
        self.assertEqual(profile["resolution"]["match_method"], "unresolved")
        self.assertEqual(profile["works"], [])
        self.assertEqual(profile["claims"], [])

    def test_openalex_works_failure_is_recorded(self):
        # Arrange: author resolves but the works listing errors.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {"results": [oa_author_record()]}
        client.get_works_typed.side_effect = RuntimeError("works api down")
        # Act
        profile = builder.build_expert_profile(
            make_expert(affiliation="Stanford University"), oa_client=client
        )
        # Assert: the profile still builds; the failure is recorded, not raised.
        self.assertEqual(profile["works"], [])
        self.assertTrue(any(e.startswith("openalex-works") for e in profile["errors"]))


class StoreProfileTests(TestCase):
    @patch("research_ai.services.researcher_profile.builder.build_expert_profile")
    def test_build_and_store_persists_profile(self, mock_build):
        # Arrange
        mock_build.return_value = {"schema_version": 1, "claims": []}
        expert = Expert.objects.create(email="jane@example.com", first_name="Jane")
        # Act
        returned = builder.build_and_store_expert_profile(expert)
        # Assert
        expert.refresh_from_db()
        self.assertEqual(expert.profile, {"schema_version": 1, "claims": []})
        self.assertEqual(returned, expert.profile)
        mock_build.assert_called_once_with(expert)
