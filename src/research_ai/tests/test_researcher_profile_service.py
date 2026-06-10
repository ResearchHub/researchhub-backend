"""Unit tests for researcher_profile_service (Part 1: the profile builder)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from research_ai.models import Expert
from research_ai.services import researcher_profile_service as svc


def _expert(**kwargs):
    """Duck-typed Expert stand-in (no DB) for the pure-logic paths."""
    defaults = {
        "first_name": "Jane",
        "middle_name": "",
        "last_name": "Doe",
        "affiliation": "",
        "expertise": "",
        "sources": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _oa_author_record(**overrides):
    record = {
        "id": "https://openalex.org/A123",
        "display_name": "Jane Doe",
        "display_name_alternatives": [],
        "orcid": "https://orcid.org/0000-0002-1825-0097",
        "summary_stats": {"h_index": 12, "i10_index": 5, "2yr_mean_citedness": 2.1},
        "works_count": 40,
        "cited_by_count": 900,
        "affiliations": [{"institution": {"display_name": "Stanford University"}}],
        "topics": [{"display_name": "Genomics"}, {"display_name": "Bioinformatics"}],
    }
    record.update(overrides)
    return record


def _orcid_work(title, year=None):
    ws = {"title": {"title": {"value": title}}}
    if year:
        ws["publication-date"] = {"year": {"value": year}}
    return ws


def _oa_work(title, year, position, author_id="https://openalex.org/A123"):
    slug = title.lower().replace(" ", "-")
    return {
        "display_name": title,
        "publication_year": year,
        "doi": f"https://doi.org/10.1/{slug}",
        "id": f"https://openalex.org/W-{slug}",
        "authorships": [{"author": {"id": author_id}, "author_position": position}],
    }


class ResolverHelpersTests(SimpleTestCase):
    def test_extract_ids_from_sources(self):
        # Arrange
        expert = _expert(
            sources=[
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
                {"text": "OpenAlex", "url": "https://openalex.org/A5023888391"},
            ]
        )
        # Act
        orcid, oa_id = svc._extract_ids_from_sources(expert)
        # Assert
        self.assertEqual(orcid, "0000-0002-1825-0097")
        self.assertEqual(oa_id, "A5023888391")

    def test_extract_ids_handles_plain_string_sources_and_misses(self):
        # Arrange
        expert = _expert(sources=["https://example.edu/jane", "not a url"])
        # Act
        orcid, oa_id = svc._extract_ids_from_sources(expert)
        # Assert
        self.assertIsNone(orcid)
        self.assertIsNone(oa_id)

    def test_name_score_exact_initial_and_lastname_only(self):
        # Arrange
        expert = _expert(first_name="Jane", last_name="Doe")
        # Act / Assert
        self.assertEqual(svc._name_score(expert, {"display_name": "Jane Doe"}), 1.0)
        self.assertEqual(svc._name_score(expert, {"display_name": "J. Doe"}), 0.6)
        # A different first name still shares the "J" initial -> weak match, not 0.
        self.assertGreater(svc._name_score(expert, {"display_name": "Doe"}), 0.0)
        self.assertEqual(svc._name_score(expert, {"display_name": "John Smith"}), 0.0)

    def test_name_score_uses_alternatives(self):
        # Arrange
        expert = _expert(first_name="Jane", last_name="Doe")
        record = {"display_name": "J Doe", "display_name_alternatives": ["Jane Doe"]}
        # Act / Assert
        self.assertEqual(svc._name_score(expert, record), 1.0)

    def test_affiliation_score_overlap_and_no_overlap(self):
        # Arrange
        expert = _expert(affiliation="Stanford University, Dept of Biology")
        match = {
            "affiliations": [{"institution": {"display_name": "Stanford University"}}]
        }
        miss = {
            "affiliations": [{"institution": {"display_name": "Harvard University"}}]
        }
        # Act / Assert
        self.assertGreaterEqual(svc._affiliation_score(expert, match), 0.34)
        self.assertEqual(svc._affiliation_score(expert, miss), 0.0)
        # No affiliation on the expert -> neutral 0.
        self.assertEqual(svc._affiliation_score(_expert(), match), 0.0)


class ResolveOpenAlexAuthorTests(SimpleTestCase):
    @patch(
        "research_ai.services.researcher_profile_service.fetch_openalex_author_record"
    )
    def test_resolves_from_source_link(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = _oa_author_record()
        expert = _expert(sources=[{"url": "https://orcid.org/0000-0002-1825-0097"}])
        # Act
        res = svc.resolve_openalex_author(expert, client=MagicMock())
        # Assert
        self.assertEqual(res.match_method, "source-link")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")
        self.assertEqual(res.orcid, "0000-0002-1825-0097")
        self.assertEqual(res.match_score, 1.0)

    def test_resolves_by_name_and_affiliation(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": [_oa_author_record()]}
        expert = _expert(affiliation="Stanford University")
        # Act
        res = svc.resolve_openalex_author(expert, client=client)
        # Assert
        self.assertEqual(res.match_method, "name+affiliation")
        self.assertEqual(res.openalex_author_id, "https://openalex.org/A123")
        self.assertIsNotNone(res.record)
        client.search_authors_via_name.assert_called_once()

    def test_unresolved_when_affiliation_ambiguous(self):
        # Arrange: two exact-name authors, neither matching the expert's affiliation.
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [
                _oa_author_record(
                    id="https://openalex.org/A1",
                    affiliations=[{"institution": {"display_name": "Harvard"}}],
                ),
                _oa_author_record(
                    id="https://openalex.org/A2",
                    affiliations=[{"institution": {"display_name": "Yale"}}],
                ),
            ]
        }
        expert = _expert(affiliation="Stanford University")
        # Act
        res = svc.resolve_openalex_author(expert, client=client)
        # Assert
        self.assertEqual(res.match_method, "unresolved")
        self.assertEqual(res.candidates_considered, 2)

    def test_unresolved_search_error_is_captured(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.side_effect = RuntimeError("network")
        # Act
        res = svc.resolve_openalex_author(_expert(), client=client)
        # Assert
        self.assertEqual(res.match_method, "unresolved")
        self.assertIn("network", res.error or "")

    def test_single_exact_name_match_without_affiliation(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": [_oa_author_record()]}
        # Act: expert has no affiliation, only one strong candidate -> accept by name.
        res = svc.resolve_openalex_author(_expert(), client=client)
        # Assert
        self.assertEqual(res.match_method, "name")


class StructuredExtractorTests(SimpleTestCase):
    def test_extract_metrics(self):
        # Act
        metrics = svc._extract_metrics(_oa_author_record())
        # Assert
        self.assertEqual(metrics["h_index"], 12)
        self.assertEqual(metrics["i10_index"], 5)
        self.assertEqual(metrics["works_count"], 40)
        self.assertEqual(metrics["cited_by_count"], 900)
        self.assertEqual(metrics["source_url"], "https://openalex.org/A123")

    def test_extract_metrics_empty_when_no_stats(self):
        # Arrange
        record = {"id": "https://openalex.org/A1", "summary_stats": {}}
        # Act / Assert
        self.assertEqual(svc._extract_metrics(record), {})
        self.assertEqual(svc._extract_metrics(None), {})

    def test_extract_affiliations_and_topics(self):
        # Act
        affs = svc._extract_affiliations(_oa_author_record())
        topics = svc._extract_topics(_oa_author_record())
        # Assert
        self.assertEqual(affs, ["Stanford University"])
        self.assertEqual(topics, ["Genomics", "Bioinformatics"])

    def test_extract_orcid_works_prefers_doi_url(self):
        # Arrange
        works_json = {
            "group": [
                {
                    "work-summary": [
                        {
                            "title": {"title": {"value": "A Paper"}},
                            "publication-date": {"year": {"value": "2021"}},
                            "external-ids": {
                                "external-id": [
                                    {
                                        "external-id-type": "doi",
                                        "external-id-value": "10.1/abc",
                                    }
                                ]
                            },
                        },
                        {
                            "title": {"title": {"value": "No Source Paper"}},
                        },
                    ]
                }
            ]
        }
        # Act
        works = svc._extract_orcid_works(works_json, "https://orcid.org/0000")
        # Assert
        self.assertEqual(len(works), 2)
        self.assertEqual(works[0]["source_url"], "https://doi.org/10.1/abc")
        self.assertEqual(works[0]["year"], "2021")
        # Falls back to the ORCID record URL when a work has no DOI/url.
        self.assertEqual(works[1]["source_url"], "https://orcid.org/0000")

    def test_extract_orcid_works_drops_when_no_url_available(self):
        # Arrange
        works_json = {"group": [{"work-summary": [{"title": {"value": "X"}}]}]}
        # Act
        works = svc._extract_orcid_works(works_json, None)
        # Assert
        self.assertEqual(works, [])

    def test_extract_orcid_works_keeps_most_recent_five(self):
        # Arrange: seven works in ORCID payload order, years shuffled, one undated.
        years = ["2018", "2024", None, "2020", "2025", "2019", "2022"]
        works_json = {
            "group": [
                {"work-summary": [_orcid_work(f"Paper {i}", year=year)]}
                for i, year in enumerate(years)
            ]
        }
        # Act
        works = svc._extract_orcid_works(works_json, "https://orcid.org/0000")
        # Assert: the five newest, most recent first; undated and oldest dropped.
        self.assertEqual(
            [w["year"] for w in works], ["2025", "2024", "2022", "2020", "2019"]
        )

    def test_extract_orcid_works_dedupes_same_work_across_sources(self):
        # Arrange: one group claiming the same work from two sources.
        works_json = {
            "group": [
                {
                    "work-summary": [
                        _orcid_work("Same Paper", year="2023"),
                        _orcid_work("Same Paper", year="2023"),
                    ]
                }
            ]
        }
        # Act
        works = svc._extract_orcid_works(works_json, "https://orcid.org/0000")
        # Assert
        self.assertEqual(len(works), 1)

    def test_extract_openalex_works_maps_fields_and_author_position(self):
        # Arrange: second work has no DOI and lists this author mid-list by bare id.
        results = [
            _oa_work("Lead Paper", 2024, "first"),
            {
                "display_name": "Middle Paper",
                "publication_year": 2023,
                "doi": None,
                "id": "https://openalex.org/W2",
                "authorships": [
                    {
                        "author": {"id": "https://openalex.org/A999"},
                        "author_position": "first",
                    },
                    {"author": {"id": "A123"}, "author_position": "middle"},
                ],
            },
        ]
        # Act
        works = svc._extract_openalex_works(results, "https://openalex.org/A123")
        # Assert
        self.assertEqual(works[0]["author_position"], "first")
        self.assertEqual(works[0]["source_url"], "https://doi.org/10.1/lead-paper")
        # Falls back to the OpenAlex work URL when there is no DOI.
        self.assertEqual(works[1]["source_url"], "https://openalex.org/W2")
        self.assertEqual(works[1]["author_position"], "middle")

    def test_select_works_prioritizes_first_and_last_author(self):
        # Arrange: seven works; the lead/senior-author papers are the older ones.
        results = [
            _oa_work("Middle A", 2025, "middle"),
            _oa_work("Middle B", 2024, "middle"),
            _oa_work("First Old", 2019, "first"),
            _oa_work("Last Older", 2018, "last"),
            _oa_work("Middle C", 2022, "middle"),
            _oa_work("First New", 2023, "first"),
            _oa_work("Middle D", 2021, "middle"),
        ]
        # Act
        works = svc._select_works(svc._extract_openalex_works(results, "A123"))
        # Assert: every first/last paper kept (newest first), middles fill the rest.
        self.assertEqual(
            [w["title"] for w in works],
            ["First New", "First Old", "Last Older", "Middle A", "Middle B"],
        )


class WebFindingsParseTests(SimpleTestCase):
    def test_parses_valid_findings_and_drops_unsourced(self):
        # Arrange
        raw = (
            '{"findings": ['
            '{"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"},'
            '{"text": "No source claim", "url": ""},'
            '{"text": "", "url": "https://x.edu"}'
            "]}"
        )
        # Act
        findings = svc._parse_web_findings(raw)
        # Assert
        self.assertEqual(
            findings, [{"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"}]
        )

    def test_parses_findings_from_code_fence(self):
        # Arrange
        raw = '```json\n{"findings": [{"text": "Talk at NIH", "url": "https://nih.gov/t"}]}\n```'
        # Act
        findings = svc._parse_web_findings(raw)
        # Assert
        self.assertEqual(
            findings, [{"text": "Talk at NIH", "url": "https://nih.gov/t"}]
        )

    def test_invalid_json_returns_empty(self):
        # Act / Assert
        self.assertEqual(svc._parse_web_findings("not json at all"), [])
        self.assertEqual(svc._parse_web_findings(""), [])


class ClaimsTests(SimpleTestCase):
    def test_every_claim_has_url_and_dedupes(self):
        # Act
        claims = svc._build_claims(
            author_url="https://openalex.org/A123",
            metrics={
                "h_index": 12,
                "i10_index": 5,
                "works_count": 40,
                "cited_by_count": 900,
                "source_url": "https://openalex.org/A123",
            },
            affiliations=["Stanford University"],
            topics=["Genomics"],
            works=[
                {
                    "title": "A Paper",
                    "year": "2021",
                    "source_url": "https://doi.org/10.1/abc",
                }
            ],
            web_findings=[
                {"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"},
                {"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"},  # dup
            ],
        )
        # Assert
        self.assertTrue(all(svc._is_http_url(c["url"]) for c in claims))
        texts = [c["text"] for c in claims]
        self.assertIn("Affiliation (OpenAlex): Stanford University", texts)
        self.assertIn("Research topics (OpenAlex): Genomics", texts)
        self.assertIn("(2021) A Paper", texts)
        self.assertEqual(texts.count("Runs the Doe Lab"), 1)

    def test_openalex_claims_dropped_without_author_url(self):
        # Act: no author_url -> OpenAlex-derived claims have no URL and are dropped.
        claims = svc._build_claims(
            author_url=None,
            metrics={
                "h_index": 12,
                "i10_index": 5,
                "works_count": 1,
                "cited_by_count": 2,
                "source_url": None,
            },
            affiliations=["Stanford University"],
            topics=["Genomics"],
            works=[],
            web_findings=[],
        )
        # Assert
        self.assertEqual(claims, [])


class BuildProfileTests(SimpleTestCase):
    def test_builds_full_profile_from_name_match_with_web_search(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [_oa_author_record(orcid=None)]
        }
        client.get_works.return_value = ([_oa_work("Lead Paper", 2024, "first")], None)
        openai_service = MagicMock()
        openai_service.invoke.return_value = (
            '{"findings": [{"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"}]}'
        )
        expert = _expert(affiliation="Stanford University", expertise="genomics")
        # Act
        profile = svc.build_expert_profile(
            expert, oa_client=client, openai_service=openai_service
        )
        # Assert
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["resolution"]["match_method"], "name+affiliation")
        self.assertEqual(profile["metrics"]["h_index"], 12)
        self.assertEqual(profile["affiliations"], ["Stanford University"])
        self.assertEqual(profile["works"][0]["author_position"], "first")
        self.assertIn(
            {"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"},
            profile["web_findings"],
        )
        # Authorship position is surfaced on the work's claim text.
        self.assertIn(
            "(2024) Lead Paper [first author]",
            [c["text"] for c in profile["claims"]],
        )
        self.assertTrue(all(svc._is_http_url(c["url"]) for c in profile["claims"]))
        self.assertIn("Additional background (web search", profile["context_text"])
        self.assertEqual(profile["errors"], [])

    def test_web_search_disabled_skips_openai(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        openai_service = MagicMock()
        # Act
        profile = svc.build_expert_profile(
            _expert(),
            oa_client=client,
            openai_service=openai_service,
            use_web_search=False,
        )
        # Assert
        openai_service.invoke.assert_not_called()
        self.assertEqual(profile["resolution"]["match_method"], "unresolved")
        self.assertEqual(profile["web_findings"], [])
        self.assertEqual(profile["claims"], [])

    def test_web_search_failure_is_non_fatal(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [_oa_author_record(orcid=None)]
        }
        client.get_works.return_value = ([], None)
        openai_service = MagicMock()
        openai_service.invoke.side_effect = RuntimeError("openai down")
        # Act
        profile = svc.build_expert_profile(
            _expert(affiliation="Stanford University"),
            oa_client=client,
            openai_service=openai_service,
        )
        # Assert: resolution still succeeded; the failure is recorded, not raised.
        self.assertEqual(profile["resolution"]["match_method"], "name+affiliation")
        self.assertEqual(profile["web_findings"], [])
        self.assertTrue(any("web_search" in e for e in profile["errors"]))

    @patch("research_ai.services.researcher_profile_service.fetch_orcid_works")
    def test_falls_back_to_orcid_works_when_openalex_works_fail(self, mock_orcid):
        # Arrange: author resolves (with an ORCID) but the works listing errors.
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": [_oa_author_record()]}
        client.get_works.side_effect = RuntimeError("works api down")
        mock_orcid.return_value = {
            "group": [{"work-summary": [_orcid_work("Fallback Paper", year="2020")]}]
        }
        # Act
        profile = svc.build_expert_profile(
            _expert(affiliation="Stanford University"),
            oa_client=client,
            openai_service=MagicMock(),
            use_web_search=False,
        )
        # Assert: ORCID works fill in and the OpenAlex failure is recorded.
        self.assertEqual(profile["works"][0]["title"], "Fallback Paper")
        self.assertIsNone(profile["works"][0]["author_position"])
        self.assertTrue(any(e.startswith("openalex-works") for e in profile["errors"]))


class StoreProfileTests(TestCase):
    @patch("research_ai.services.researcher_profile_service.build_expert_profile")
    def test_build_and_store_persists_profile(self, mock_build):
        # Arrange
        mock_build.return_value = {"schema_version": 1, "claims": []}
        expert = Expert.objects.create(email="jane@example.com", first_name="Jane")
        # Act
        returned = svc.build_and_store_expert_profile(expert, use_web_search=False)
        # Assert
        expert.refresh_from_db()
        self.assertEqual(expert.profile, {"schema_version": 1, "claims": []})
        self.assertEqual(returned, expert.profile)
        mock_build.assert_called_once_with(expert, use_web_search=False)
