"""Unit tests for researcher_profile.builder (assembly + entry points)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from research_ai.models import Expert
from research_ai.services.researcher_profile import builder
from research_ai.services.researcher_profile.common import is_http_url
from research_ai.tests.researcher_profile.helpers import (
    make_expert,
    oa_author_record,
    oa_work,
    orcid_work,
)


class RecordExtractorTests(SimpleTestCase):
    def test_extract_metrics(self):
        # Act
        metrics = builder._extract_metrics(oa_author_record())
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
        self.assertEqual(builder._extract_metrics(record), {})
        self.assertEqual(builder._extract_metrics(None), {})

    def test_extract_affiliations_and_topics(self):
        # Act
        affs = builder._extract_affiliations(oa_author_record())
        topics = builder._extract_topics(oa_author_record())
        # Assert
        self.assertEqual(affs, ["Stanford University"])
        self.assertEqual(topics, ["Genomics", "Bioinformatics"])


class ClaimsTests(SimpleTestCase):
    def test_every_claim_has_url_and_dedupes(self):
        # Act
        claims = builder._build_claims(
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
        self.assertTrue(all(is_http_url(c["url"]) for c in claims))
        texts = [c["text"] for c in claims]
        self.assertIn("Affiliation (OpenAlex): Stanford University", texts)
        self.assertIn("Research topics (OpenAlex): Genomics", texts)
        self.assertIn("(2021) A Paper", texts)
        self.assertEqual(texts.count("Runs the Doe Lab"), 1)

    def test_openalex_claims_dropped_without_author_url(self):
        # Act: no author_url -> OpenAlex-derived claims have no URL and are dropped.
        claims = builder._build_claims(
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
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [oa_author_record(orcid=None)]
        }
        client.get_works.return_value = ([oa_work("Lead Paper", 2024, "first")], None)
        openai_service = MagicMock()
        openai_service.invoke.return_value = (
            '{"findings": [{"text": "Runs the Doe Lab", "url": "https://doe-lab.edu"}]}'
        )
        expert = make_expert(affiliation="Stanford University", expertise="genomics")
        # Act
        profile = builder.build_expert_profile(
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
        self.assertTrue(all(is_http_url(c["url"]) for c in profile["claims"]))
        self.assertIn("Additional background (web search", profile["context_text"])
        self.assertEqual(profile["errors"], [])

    def test_web_search_disabled_skips_openai(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {"results": []}
        openai_service = MagicMock()
        # Act
        profile = builder.build_expert_profile(
            make_expert(),
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
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {
            "results": [oa_author_record(orcid=None)]
        }
        client.get_works.return_value = ([], None)
        openai_service = MagicMock()
        openai_service.invoke.side_effect = RuntimeError("openai down")
        # Act
        profile = builder.build_expert_profile(
            make_expert(affiliation="Stanford University"),
            oa_client=client,
            openai_service=openai_service,
        )
        # Assert: resolution still succeeded; the failure is recorded, not raised.
        self.assertEqual(profile["resolution"]["match_method"], "name+affiliation")
        self.assertEqual(profile["web_findings"], [])
        self.assertTrue(any("web_search" in e for e in profile["errors"]))

    @patch("research_ai.services.researcher_profile.works.fetch_orcid_works")
    def test_falls_back_to_orcid_works_when_openalex_works_fail(self, mock_orcid):
        # Arrange: author resolves (with an ORCID) but the works listing errors.
        client = MagicMock()
        client.search_institutions.return_value = {
            "results": [{"id": "https://openalex.org/I1"}]
        }
        client.search_authors_via_name.return_value = {"results": [oa_author_record()]}
        client.get_works.side_effect = RuntimeError("works api down")
        mock_orcid.return_value = {
            "group": [{"work-summary": [orcid_work("Fallback Paper", year="2020")]}]
        }
        # Act
        profile = builder.build_expert_profile(
            make_expert(affiliation="Stanford University"),
            oa_client=client,
            openai_service=MagicMock(),
            use_web_search=False,
        )
        # Assert: ORCID works fill in and the OpenAlex failure is recorded.
        self.assertEqual(profile["works"][0]["title"], "Fallback Paper")
        self.assertIsNone(profile["works"][0]["author_position"])
        self.assertTrue(any(e.startswith("openalex-works") for e in profile["errors"]))


class StoreProfileTests(TestCase):
    @patch("research_ai.services.researcher_profile.builder.build_expert_profile")
    def test_build_and_store_persists_profile(self, mock_build):
        # Arrange
        mock_build.return_value = {"schema_version": 1, "claims": []}
        expert = Expert.objects.create(email="jane@example.com", first_name="Jane")
        # Act
        returned = builder.build_and_store_expert_profile(expert, use_web_search=False)
        # Assert
        expert.refresh_from_db()
        self.assertEqual(expert.profile, {"schema_version": 1, "claims": []})
        self.assertEqual(returned, expert.profile)
        mock_build.assert_called_once_with(expert, use_web_search=False)
