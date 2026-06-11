"""Unit tests for researcher_profile.resolver."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import resolver
from research_ai.tests.researcher_profile.helpers import make_expert, oa_author_record


class ResolverHelpersTests(SimpleTestCase):
    def test_name_score_exact_initial_and_lastname_only(self):
        # Arrange
        expert = make_expert(first_name="Jane", last_name="Doe")
        # Act / Assert
        self.assertEqual(
            resolver._name_score(expert, {"display_name": "Jane Doe"}), 1.0
        )
        self.assertEqual(resolver._name_score(expert, {"display_name": "J. Doe"}), 0.6)
        # A different first name still shares the "J" initial -> weak match, not 0.
        self.assertGreater(resolver._name_score(expert, {"display_name": "Doe"}), 0.0)
        self.assertEqual(
            resolver._name_score(expert, {"display_name": "John Smith"}), 0.0
        )

    def test_name_score_uses_alternatives(self):
        # Arrange
        expert = make_expert(first_name="Jane", last_name="Doe")
        record = {"display_name": "J Doe", "display_name_alternatives": ["Jane Doe"]}
        # Act / Assert
        self.assertEqual(resolver._name_score(expert, record), 1.0)

    def test_name_score_handles_compound_surnames(self):
        # Arrange: hyphenated and multi-word last names span several tokens.
        garcia = make_expert(first_name="Jane", last_name="García-López")
        vandenberg = make_expert(first_name="Jan", last_name="van der Berg")
        # Act / Assert
        self.assertEqual(
            resolver._name_score(garcia, {"display_name": "Jane Garcia-Lopez"}), 1.0
        )
        self.assertEqual(
            resolver._name_score(vandenberg, {"display_name": "J. van der Berg"}), 0.6
        )
        # A different particle is a different surname.
        self.assertEqual(
            resolver._name_score(vandenberg, {"display_name": "Jan van den Berg"}), 0.0
        )


class ResolveOpenAlexAuthorTests(SimpleTestCase):
    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_resolves_from_source_link(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = oa_author_record()
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res = resolver.resolve_openalex_author(expert, client=MagicMock())
        # Assert
        self.assertEqual(res.match_method, "source-link")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")
        self.assertEqual(res.match_score, 1.0)
        # The cited ORCID is only a lookup key into OpenAlex.
        mock_fetch.assert_called_once()
        self.assertEqual(
            mock_fetch.call_args.kwargs["orcid_bare"], "0000-0002-1825-0097"
        )

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_source_link_miss_falls_through_to_name_search(self, mock_fetch):
        # Arrange: OpenAlex has no author behind the cited ORCID.
        mock_fetch.return_value = None
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": [oa_author_record()]}
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res = resolver.resolve_openalex_author(expert, client=client)
        # Assert: resolved by the unscoped single-exact-name rung instead.
        self.assertEqual(res.match_method, "name")

    def test_resolves_by_name_scoped_to_institution(self):
        # Arrange: OpenAlex resolves the affiliation string to an institution id,
        # and the author search is scoped to it.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I114027177"}]
        }
        client.search_authors_via_name.return_value = {"results": [oa_author_record()]}
        expert = make_expert(affiliation="Stanford University")
        # Act
        res = resolver.resolve_openalex_author(expert, client=client)
        # Assert
        self.assertEqual(res.match_method, "name+affiliation")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")
        self.assertEqual(res.match_score, 1.0)
        self.assertIsNotNone(res.record)
        client.search_institutions.assert_called_once_with("Stanford University")
        client.search_authors_via_name.assert_called_once_with(
            "Jane Doe", institution_id="https://openalex.org/I114027177"
        )

    def test_falls_back_to_unscoped_search_when_institution_unknown(self):
        # Arrange: institution search finds nothing usable.
        client = MagicMock()
        client.search_institutions.return_value = {"results": []}
        client.search_authors_via_name.return_value = {"results": [oa_author_record()]}
        expert = make_expert(affiliation="Tiny Unknown Lab")
        # Act
        res = resolver.resolve_openalex_author(expert, client=client)
        # Assert: single exact full-name match accepted by name alone.
        self.assertEqual(res.match_method, "name")
        client.search_authors_via_name.assert_called_once_with("Jane Doe")

    def test_moved_researcher_resolves_via_unscoped_search(self):
        # Arrange: the institution resolves but the author isn't affiliated with
        # it in OpenAlex (e.g. they moved) -> scoped search is empty.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.side_effect = [
            {"results": []},  # scoped
            {"results": [oa_author_record()]},  # unscoped
        ]
        expert = make_expert(affiliation="Stanford University")
        # Act
        res = resolver.resolve_openalex_author(expert, client=client)
        # Assert
        self.assertEqual(res.match_method, "name")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")

    def test_ambiguous_candidates_unresolved_when_adjudicator_declines(self):
        # Arrange: two exact-name candidates, no affiliation to scope by.
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                oa_author_record(id="https://openalex.org/A1"),
                oa_author_record(id="https://openalex.org/A2"),
            ]
        }
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"candidate_index": null, "confidence": 0.2, "reason": "ambiguous"}'
        )
        # Act
        res = resolver.resolve_openalex_author(
            make_expert(), client=client, adjudication_service=llm
        )
        # Assert
        self.assertEqual(res.match_method, "unresolved")
        self.assertEqual(res.candidates_considered, 2)

    def test_ambiguous_candidates_resolved_by_adjudication(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                oa_author_record(id="https://openalex.org/A1"),
                oa_author_record(id="https://openalex.org/A2"),
            ]
        }
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"candidate_index": 1, "confidence": 0.9, "reason": "topics match"}'
        )
        # Act
        res = resolver.resolve_openalex_author(
            make_expert(), client=client, adjudication_service=llm
        )
        # Assert
        self.assertEqual(res.match_method, "llm-adjudicated")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A2")
        self.assertEqual(res.match_score, 0.9)

    def test_adjudication_failure_is_unresolved(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                oa_author_record(id="https://openalex.org/A1"),
                oa_author_record(id="https://openalex.org/A2"),
            ]
        }
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("bedrock down")
        # Act
        res = resolver.resolve_openalex_author(
            make_expert(), client=client, adjudication_service=llm
        )
        # Assert: failure is recorded, never guessed around.
        self.assertEqual(res.match_method, "unresolved")
        self.assertIn("bedrock down", res.error or "")

    def test_unresolved_search_error_is_captured(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.side_effect = RuntimeError("network")
        # Act
        res = resolver.resolve_openalex_author(make_expert(), client=client)
        # Assert
        self.assertEqual(res.match_method, "unresolved")
        self.assertIn("network", res.error or "")

    def test_single_exact_name_match_without_affiliation(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": [oa_author_record()]}
        # Act: expert has no affiliation, only one strong candidate -> accept by name.
        res = resolver.resolve_openalex_author(make_expert(), client=client)
        # Assert
        self.assertEqual(res.match_method, "name")
