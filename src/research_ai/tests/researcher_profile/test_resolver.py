"""Unit tests for researcher_profile.resolver."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import resolver
from research_ai.tests.researcher_profile.helpers import make_expert
from utils.tests.openalex_helpers import create_oa_author_record


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


class ResolveAuthorTests(SimpleTestCase):
    """The full escalation ladder, exercised through ``resolve_author``."""

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_resolves_from_source_link(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = create_oa_author_record()
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res, disamb, errors = resolver.resolve_author(expert, client=MagicMock())
        # Assert
        self.assertEqual(res.match_method, "source-link")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")
        self.assertEqual(res.match_score, 1.0)
        # No name candidates gathered -> the LLM was never consulted.
        self.assertIsNone(disamb)
        self.assertEqual(errors, [])
        # The cited ORCID is only a lookup key into OpenAlex.
        mock_fetch.assert_called_once()
        self.assertEqual(
            mock_fetch.call_args.kwargs["orcid_bare"], "0000-0002-1825-0097"
        )

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_source_link_miss_falls_through_to_name_search(self, mock_fetch):
        # Arrange: OpenAlex has no author behind the cited ORCID, so the expert
        # falls through to the name rungs. A name-only match escalates to the LLM.
        mock_fetch.return_value = None
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        llm = MagicMock()
        llm.invoke.return_value = '{"choice": 0, "confidence": 0.9, "reasoning": "x"}'
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res, _, _ = resolver.resolve_author(expert, client=client, llm=llm)
        # Assert: resolved by the disambiguator, not auto-accepted on name alone.
        self.assertEqual(res.match_method, "name-llm")

    def test_resolves_by_name_scoped_to_institution(self):
        # Arrange: OpenAlex resolves the affiliation string to an institution id,
        # and the author search is scoped to it.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I114027177"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        expert = make_expert(affiliation="Stanford University")
        # Act
        res, _, _ = resolver.resolve_author(expert, client=client)
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
        # Arrange: institution search finds nothing usable, so the match is
        # name-only (unscoped) and must be adjudicated by the disambiguator.
        client = MagicMock()
        client.search_institutions.return_value = {"results": []}
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        llm = MagicMock()
        llm.invoke.return_value = '{"choice": 0, "confidence": 0.9, "reasoning": "x"}'
        expert = make_expert(affiliation="Tiny Unknown Lab")
        # Act
        res, _, _ = resolver.resolve_author(expert, client=client, llm=llm)
        # Assert: name-only is never auto-accepted -> escalated.
        self.assertEqual(res.match_method, "name-llm")
        client.search_authors_via_name.assert_called_once_with("Jane Doe")

    def test_moved_researcher_resolves_via_unscoped_search(self):
        # Arrange: the institution resolves but the author isn't affiliated with
        # it in OpenAlex (e.g. they moved) -> scoped search is empty, so the
        # unscoped (name-only) hit is adjudicated by the disambiguator.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.side_effect = [
            {"results": []},  # scoped
            {"results": [create_oa_author_record()]},  # unscoped
        ]
        llm = MagicMock()
        llm.invoke.return_value = '{"choice": 0, "confidence": 0.9, "reasoning": "x"}'
        expert = make_expert(affiliation="Stanford University")
        # Act
        res, _, _ = resolver.resolve_author(expert, client=client, llm=llm)
        # Assert
        self.assertEqual(res.match_method, "name-llm")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")

    def test_ambiguous_candidates_escalate_to_llm(self):
        # Arrange: two exact-name candidates, no affiliation to scope by. The
        # ladder does NOT take the top -- it hands the set to the disambiguator.
        client = MagicMock()
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
        llm = MagicMock()
        # Candidates are sorted by citation count, so index 0 is the 900-cite A2.
        llm.invoke.return_value = (
            '{"choice": 0, "confidence": 0.91, "reasoning": "topics match"}'
        )
        # Act
        res, disamb, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert: the LLM adjudicated and its pick won.
        self.assertEqual(res.match_method, "name-llm")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A2")
        self.assertEqual(res.candidates_considered, 2)
        self.assertTrue(disamb.chosen)
        llm.invoke.assert_called_once()

    def test_llm_abstains_leaves_unresolved(self):
        # Arrange: ambiguous candidates the LLM declines to disambiguate.
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                create_oa_author_record(id="https://openalex.org/A1"),
                create_oa_author_record(id="https://openalex.org/A2"),
            ]
        }
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "confidence": 0.2, "reasoning": "unsure"}'
        )
        # Act
        res, disamb, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert: left unresolved rather than guessed; abstain surfaced for audit.
        self.assertEqual(res.match_method, "unresolved")
        self.assertFalse(disamb.chosen)

    def test_low_confidence_llm_choice_leaves_unresolved(self):
        # Arrange: the model picks a candidate, but reports too little confidence to
        # attach that candidate's papers to the expert.
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                create_oa_author_record(id="https://openalex.org/A1"),
                create_oa_author_record(id="https://openalex.org/A2"),
            ]
        }
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": 0, "confidence": 0.2, "reasoning": "weak match"}'
        )
        # Act
        res, disamb, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert: treated as an abstain for profile-building purposes.
        self.assertEqual(res.match_method, "unresolved")
        self.assertFalse(disamb.chosen)
        self.assertEqual(disamb.confidence, 0.2)

    def test_unresolved_search_error_is_captured(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.side_effect = RuntimeError("network")
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "confidence": 0.1, "reasoning": "x"}'
        )
        # Act
        res, _, errors = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert: the search failure surfaces in the errors list, never raised.
        self.assertEqual(res.match_method, "unresolved")
        self.assertTrue(any("network" in e for e in errors))

    def test_name_only_match_escalates_to_disambiguator(self):
        # Arrange: expert has no affiliation, one strong candidate -> name-only,
        # which is never auto-accepted; the disambiguator confirms it.
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": 0, "confidence": 0.88, "reasoning": "topics match"}'
        )
        # Act
        res, disamb, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert
        self.assertEqual(res.match_method, "name-llm")
        self.assertEqual(res.match_score, 0.88)
        self.assertTrue(disamb.chosen)

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_web_found_identifier_is_fetched_and_accepted(self, mock_fetch):
        # Arrange: no candidate fits, but the disambiguator reports an ORCID; the
        # re-fetched record's name validates, so it resolves as web-id.
        mock_fetch.return_value = create_oa_author_record(id="https://openalex.org/A9")
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record(id="https://openalex.org/A1")]
        }
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "orcid": "0000-0002-1825-0097", '
            '"confidence": 0.8, "reasoning": "moved"}'
        )
        # Act
        res, disamb, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert
        self.assertEqual(res.match_method, "web-id")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A9")
        self.assertEqual(res.match_score, resolver.WEB_ID_SCORE)
        # ORCID is mined to a bare key for the OpenAlex lookup.
        self.assertEqual(
            mock_fetch.call_args.kwargs["orcid_bare"], "0000-0002-1825-0097"
        )

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_web_found_identifier_rejected_when_name_mismatches(self, mock_fetch):
        # Arrange: the reported id resolves to someone with a different name ->
        # rejected as a likely hallucination, expert left unresolved.
        mock_fetch.return_value = create_oa_author_record(display_name="John Smith")
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "openalex_id": "https://openalex.org/A9", '
            '"confidence": 0.8, "reasoning": "x"}'
        )
        # Act
        res, _, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert
        self.assertEqual(res.match_method, "unresolved")

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_web_found_identifier_rejected_when_only_initial_matches(self, mock_fetch):
        # Arrange: "John Doe" shares Jane Doe's surname and initial, but is still not
        # a strong enough name match for a web-discovered identifier.
        mock_fetch.return_value = create_oa_author_record(display_name="John Doe")
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "openalex_id": "https://openalex.org/A9", '
            '"confidence": 0.8, "reasoning": "x"}'
        )
        # Act
        res, _, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert
        self.assertEqual(res.match_method, "unresolved")

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_zero_candidates_recovered_via_web_id(self, mock_fetch):
        # Arrange: the name search finds nobody, but web search turns up an ORCID.
        mock_fetch.return_value = create_oa_author_record(id="https://openalex.org/A9")
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        llm = MagicMock()
        llm.invoke.return_value = (
            '{"choice": null, "orcid": "0000-0002-1825-0097", '
            '"confidence": 0.75, "reasoning": "found"}'
        )
        # Act
        res, _, _ = resolver.resolve_author(make_expert(), client=client, llm=llm)
        # Assert
        self.assertEqual(res.match_method, "web-id")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A9")


class ResolveViaSourceLinkTests(SimpleTestCase):
    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_returns_resolution_for_cited_id(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = create_oa_author_record()
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res = resolver.resolve_via_source_link(expert, client=MagicMock())
        # Assert
        self.assertEqual(res.match_method, "source-link")
        self.assertEqual(res.match_score, 1.0)

    def test_returns_none_when_no_id_cited(self):
        # Arrange: no sources -> nothing to look up.
        # Act
        res = resolver.resolve_via_source_link(make_expert(), client=MagicMock())
        # Assert
        self.assertIsNone(res)

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_ignores_cited_openalex_author_id(self, mock_fetch):
        # Arrange: only an OpenAlex author URL is cited (no ORCID). The finder is
        # prone to fabricating these, so they must not resolve at score 1.0.
        expert = make_expert(sources=[{"url": "https://openalex.org/A123"}])
        # Act
        res = resolver.resolve_via_source_link(expert, client=MagicMock())
        # Assert: falls through, and OpenAlex is never queried for the cited id.
        self.assertIsNone(res)
        mock_fetch.assert_not_called()

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_returns_none_when_openalex_has_no_record(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = None
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res = resolver.resolve_via_source_link(expert, client=MagicMock())
        # Assert
        self.assertIsNone(res)

    @patch(
        "research_ai.services.researcher_profile.resolver.fetch_openalex_author_record"
    )
    def test_returns_none_when_cited_orcid_name_does_not_match(self, mock_fetch):
        # Arrange: a bad source URL must not attach another person's author record
        # with source-link certainty.
        mock_fetch.return_value = create_oa_author_record(display_name="John Smith")
        expert = make_expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res = resolver.resolve_via_source_link(expert, client=MagicMock())
        # Assert
        self.assertIsNone(res)


class GatherNameCandidatesTests(SimpleTestCase):
    def test_prefers_institution_scoped_candidates(self):
        # Arrange
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        # Act
        cands = resolver.gather_name_candidates(
            make_expert(affiliation="Stanford University"), client=client
        )
        # Assert
        self.assertTrue(cands.scoped)
        self.assertEqual(len(cands.scored), 1)
        client.search_authors_via_name.assert_called_once_with(
            "Jane Doe", institution_id="https://openalex.org/I1"
        )

    def test_falls_back_to_unscoped_and_returns_all_strong_candidates(self):
        # Arrange: no affiliation -> unscoped search; two exact-name candidates.
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                create_oa_author_record(id="https://openalex.org/A1"),
                create_oa_author_record(id="https://openalex.org/A2"),
            ]
        }
        # Act
        cands = resolver.gather_name_candidates(make_expert(), client=client)
        # Assert
        self.assertFalse(cands.scoped)
        self.assertEqual(len(cands.scored), 2)
        self.assertEqual(cands.candidates_considered, 2)

    def test_search_error_is_captured(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.side_effect = RuntimeError("network")
        # Act
        cands = resolver.gather_name_candidates(make_expert(), client=client)
        # Assert
        self.assertEqual(cands.scored, [])
        self.assertIn("network", cands.error or "")


class ConfidentSingleTests(SimpleTestCase):
    def test_lone_strong_match_is_confident(self):
        # Arrange / Act / Assert
        self.assertIsNotNone(resolver.confident_single([(1.0, {"id": "A1"})]))

    def test_lone_borderline_match_is_not_confident(self):
        # Arrange: a single initial-only (0.6) match clears STRONG but not CONFIDENT.
        # Act / Assert
        self.assertIsNone(resolver.confident_single([(0.6, {"id": "A1"})]))

    def test_multiple_candidates_are_not_confident(self):
        # Arrange / Act / Assert
        self.assertIsNone(
            resolver.confident_single([(1.0, {"id": "A1"}), (1.0, {"id": "A2"})])
        )
