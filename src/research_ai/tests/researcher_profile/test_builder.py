"""Unit tests for researcher_profile.builder (escalation ladder + assembly)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from research_ai.models import Expert
from research_ai.services.researcher_profile import builder
from research_ai.tests.researcher_profile.helpers import make_expert
from utils.openalex import Work
from utils.tests.openalex_helpers import create_oa_author_record, create_oa_work


def _typed_work(title="Lead Paper", year=2024, position="first", author_id="A123"):
    entity = create_oa_work(title, year, position)
    return Work.from_openalex(entity, author_id=author_id)


class ConfidentNameRungTests(SimpleTestCase):
    def test_lone_strong_match_is_accepted_without_llm(self):
        # Arrange: one exact-name candidate scoped to a resolved institution.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record(orcid=None)]
        }
        client.get_works_typed.return_value = [_typed_work()]
        llm = MagicMock()
        expert = make_expert(affiliation="Stanford University", expertise="genomics")
        # Act
        profile = builder.build_expert_profile(expert, oa_client=client, llm=llm)
        # Assert: resolved directly; the LLM was not consulted.
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["resolution"]["match_method"], "name+affiliation")
        self.assertNotIn("disambiguation", profile["resolution"])
        self.assertEqual(profile["works"][0]["author_position"], "first")
        self.assertEqual(profile["errors"], [])
        llm.invoke.assert_not_called()


class DisambiguationRungTests(SimpleTestCase):
    def _ambiguous_client(self):
        client = MagicMock()
        # No affiliation -> unscoped search returns two exact-name candidates.
        client.search_authors_via_name.return_value = {
            "results": [
                create_oa_author_record(
                    id="https://openalex.org/A1", cited_by_count=10
                ),
                create_oa_author_record(
                    id="https://openalex.org/A2", cited_by_count=900
                ),
            ]
        }
        client.get_works_typed.return_value = [_typed_work(author_id="A2")]
        return client

    def test_ambiguous_candidates_resolved_by_llm(self):
        # Arrange
        client = self._ambiguous_client()
        llm = MagicMock()
        # Candidates are sorted by citation count, so index 0 is the 900-cite A2.
        llm.invoke.return_value = (
            '{"choice": 0, "confidence": 0.91, "reasoning": "topics match"}'
        )
        # Act
        profile = builder.build_expert_profile(make_expert(), oa_client=client, llm=llm)
        # Assert: the LLM picked candidate index 0.
        self.assertEqual(profile["resolution"]["match_method"], "name-llm")
        self.assertEqual(
            profile["resolution"]["openalex_author_id"], "https://openalex.org/A2"
        )
        self.assertEqual(profile["resolution"]["match_score"], 0.91)
        disambiguation = profile["resolution"]["disambiguation"]
        self.assertEqual(disambiguation["chosen"], True)
        self.assertEqual(disambiguation["reasoning"], "topics match")
        llm.invoke.assert_called_once()

    def test_llm_abstains_leaves_unresolved(self):
        # Arrange: the LLM cannot disambiguate the ambiguous candidates.
        client = self._ambiguous_client()
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "confidence": 0.2, "reasoning": "unsure"}'
        )
        # Act
        profile = builder.build_expert_profile(make_expert(), oa_client=client, llm=llm)
        # Assert: left unresolved rather than guessed; abstain recorded for audit.
        self.assertEqual(profile["resolution"]["match_method"], "unresolved")
        self.assertEqual(profile["works"], [])
        self.assertEqual(profile["resolution"]["disambiguation"]["chosen"], False)
        llm.invoke.assert_called_once()


class UnresolvedRungTests(SimpleTestCase):
    def test_no_candidates_leaves_unresolved_without_calling_llm(self):
        # Arrange: no name candidates at all -> nothing for the LLM to adjudicate.
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        llm = MagicMock()
        # Act
        profile = builder.build_expert_profile(make_expert(), oa_client=client, llm=llm)
        # Assert
        self.assertEqual(profile["resolution"]["match_method"], "unresolved")
        self.assertEqual(profile["works"], [])
        llm.invoke.assert_not_called()


class SourceLinkRungTests(SimpleTestCase):
    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_source_link_resolves_without_disambiguation(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = create_oa_author_record()
        client = MagicMock()
        client.get_works_typed.return_value = [_typed_work()]
        llm = MagicMock()
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        profile = builder.build_expert_profile(expert, oa_client=client, llm=llm)
        # Assert
        self.assertEqual(profile["resolution"]["match_method"], "source-link")
        self.assertNotIn("disambiguation", profile["resolution"])
        llm.invoke.assert_not_called()


class BestEffortTests(SimpleTestCase):
    def test_openalex_works_failure_is_recorded(self):
        # Arrange: author resolves but the works listing errors.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        client.get_works_typed.side_effect = RuntimeError("works api down")
        # Act
        profile = builder.build_expert_profile(
            make_expert(affiliation="Stanford University"),
            oa_client=client,
            llm=MagicMock(),
        )
        # Assert: the profile still builds; the failure is recorded, not raised.
        self.assertEqual(profile["works"], [])
        self.assertTrue(any(e.startswith("openalex-works") for e in profile["errors"]))


class StoreProfileTests(TestCase):
    @patch("research_ai.services.researcher_profile.builder.build_expert_profile")
    def test_build_and_store_persists_profile(self, mock_build):
        # Arrange
        mock_build.return_value = {"schema_version": 1, "works": []}
        expert = Expert.objects.create(email="jane@example.com", first_name="Jane")
        # Act
        returned = builder.build_and_store_expert_profile(expert)
        # Assert
        expert.refresh_from_db()
        self.assertEqual(expert.profile, {"schema_version": 1, "works": []})
        self.assertEqual(returned, expert.profile)
        mock_build.assert_called_once_with(expert)
