from unittest import TestCase as UnitTestCase
from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.models import Expert
from research_ai.services.expert_finder.profile_match import parse_profile_match_response
from research_ai.services.expert_finder.source_enrichment import (
    SourceEnrichmentService,
    build_web_profile_query,
    canonicalize_scholar_url,
    canonicalize_sources_for_expert,
    collect_profile_candidates,
    dedupe_sources_one_per_kind,
    merge_sources,
    source_kinds_present,
)


def _empty_web_search():
    client = MagicMock()
    client.configured = False
    client.search.return_value = []
    return client


def _web_search_with_results(results_by_query: dict[str, list[dict]]):
    client = MagicMock()
    client.configured = True

    def _search(query: str, *, count: int = 5):
        return list(results_by_query.get(query, []))

    client.search.side_effect = _search
    return client


def _judge_picks_first():
    judge = MagicMock()

    def _pick(*, expert, kind, candidates):
        return candidates[0]["url"] if candidates else None

    judge.pick.side_effect = _pick
    return judge


class SourceLinkHelpersTests(UnitTestCase):
    def test_merge_sources_dedupes_urls(self):
        existing = [{"text": "Faculty", "url": "https://example.edu/jane"}]
        merged = merge_sources(
            existing,
            [
                {"text": "LinkedIn", "url": "https://www.linkedin.com/in/jane/"},
                {"text": "LinkedIn", "url": "https://www.linkedin.com/in/jane"},
            ],
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]["url"], "https://www.linkedin.com/in/jane/")

    def test_source_kinds_present(self):
        kinds = source_kinds_present(
            [
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
                {"text": "X", "url": "https://x.com/jane"},
                {
                    "text": "Google Scholar",
                    "url": "https://scholar.google.com/citations?user=ABCD1234",
                },
            ]
        )
        self.assertEqual(kinds, {"orcid", "x", "google_scholar"})

    def test_canonicalize_scholar_url(self):
        self.assertEqual(
            canonicalize_scholar_url(
                "https://scholar.google.co.uk/citations?hl=en&user=ABCD1234"
                "&view_op=list_works"
            ),
            "https://scholar.google.com/citations?user=ABCD1234",
        )
        self.assertIsNone(
            canonicalize_scholar_url("https://scholar.google.com/scholar?q=jane")
        )

    def test_build_search_queries(self):
        self.assertEqual(
            build_web_profile_query(
                "linkedin",
                "Brian Gowen",
                "Research Professor",
                "Utah State University",
            ),
            "Brian Gowen Research Professor Utah State University linkedin",
        )
        self.assertEqual(
            build_web_profile_query("x", "Jane Doe", "Associate Professor", "MIT"),
            "Jane Doe Associate Professor MIT twitter",
        )
        self.assertEqual(
            build_web_profile_query(
                "google_scholar",
                "Brian Gowen",
                "Research Professor",
                "Utah State University",
            ),
            "Brian Gowen Research Professor Utah State University google scholar",
        )

    def test_collect_profile_candidates_limits_and_skips_non_profiles(self):
        results = [
            {
                "title": "News",
                "url": "https://example.edu/news/jane",
                "description": "",
            },
            {
                "title": "Jane Doe | LinkedIn",
                "url": "https://www.linkedin.com/in/jane-doe/",
                "description": "MIT",
            },
            {
                "title": "Other | LinkedIn",
                "url": "https://www.linkedin.com/in/other/",
                "description": "",
            },
            {
                "title": "Third | LinkedIn",
                "url": "https://www.linkedin.com/in/third/",
                "description": "",
            },
            {
                "title": "Fourth | LinkedIn",
                "url": "https://www.linkedin.com/in/fourth/",
                "description": "",
            },
        ]
        candidates = collect_profile_candidates(results, kind="linkedin", limit=3)
        self.assertEqual(
            [c["url"] for c in candidates],
            [
                "https://www.linkedin.com/in/jane-doe",
                "https://www.linkedin.com/in/other",
                "https://www.linkedin.com/in/third",
            ],
        )

    def test_dedupe_sources_one_per_kind(self):
        sources = [
            {"text": "Faculty", "url": "https://mit.edu/jane"},
            {"text": "X", "url": "https://x.com/janedoe"},
            {"text": "X", "url": "https://x.com/MIT"},
            {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
            {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0098"},
        ]
        deduped = dedupe_sources_one_per_kind(sources)
        self.assertEqual(len(deduped), 3)
        self.assertEqual(source_kinds_present(deduped), {"x", "orcid"})

    def test_canonicalize_sources_keeps_first_per_kind(self):
        cleaned = canonicalize_sources_for_expert(
            [
                {"text": "X", "url": "https://x.com/MIT"},
                {"text": "X", "url": "https://x.com/janedoe"},
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0098"},
            ]
        )
        self.assertEqual(
            cleaned,
            [
                {"text": "X", "url": "https://x.com/MIT"},
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
            ],
        )

    def test_parse_profile_match_response(self):
        candidates = [
            {"url": "https://x.com/wrong", "title": "A", "description": ""},
            {"url": "https://x.com/right", "title": "B", "description": ""},
        ]
        self.assertEqual(
            parse_profile_match_response('{"selected_index": 2}', candidates),
            "https://x.com/right",
        )
        self.assertIsNone(
            parse_profile_match_response('{"selected_index": null}', candidates)
        )
        self.assertIsNone(
            parse_profile_match_response('{"selected_index": 9}', candidates)
        )


class SourceEnrichmentServiceTests(TestCase):
    def test_enrich_expert_preserves_initial_sources_without_page_scan(self):
        # Arrange
        expert = Expert.objects.create(
            email="jane@mit.edu",
            first_name="Jane",
            last_name="Doe",
            affiliation="MIT",
            sources=[
                {"text": "Faculty page", "url": "https://mit.edu/jane"},
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
            ],
        )

        # Act
        changed = SourceEnrichmentService(
            web_search=_empty_web_search(),
            profile_judge=MagicMock(),
        ).enrich_expert(expert)

        # Assert
        self.assertFalse(changed)
        expert.refresh_from_db()
        self.assertEqual(
            source_kinds_present(expert.sources),
            {"orcid"},
        )

    def test_enrich_expert_web_searches_linkedin_x_and_scholar(self):
        # Arrange
        expert = Expert.objects.create(
            email="jane@mit.edu",
            first_name="Jane",
            middle_name="Q",
            last_name="Doe",
            academic_title="Associate Professor",
            affiliation="MIT",
            sources=[{"text": "Faculty page", "url": "https://mit.edu/jane"}],
        )
        linkedin_q = build_web_profile_query(
            "linkedin", "Jane Q Doe", "Associate Professor", "MIT"
        )
        x_q = build_web_profile_query(
            "x", "Jane Q Doe", "Associate Professor", "MIT"
        )
        scholar_q = build_web_profile_query(
            "google_scholar", "Jane Q Doe", "Associate Professor", "MIT"
        )
        web = _web_search_with_results(
            {
                linkedin_q: [
                    {
                        "title": "Jane Doe - MIT | LinkedIn",
                        "url": "https://www.linkedin.com/in/jane-doe",
                        "description": "Professor at MIT",
                    }
                ],
                x_q: [
                    {
                        "title": "Wrong person",
                        "url": "https://x.com/othercox",
                        "description": "Unrelated",
                    },
                    {
                        "title": "Jane Doe (@janedoe) / X",
                        "url": "https://x.com/janedoe",
                        "description": "Neuroscientist at MIT",
                    },
                ],
                scholar_q: [
                    {
                        "title": "Jane Doe - Google Scholar",
                        "url": "https://scholar.google.com/citations?user=ABCD1234&hl=en",
                        "description": "MIT",
                    }
                ],
            }
        )
        judge = MagicMock()

        def _pick(*, expert, kind, candidates):
            if kind == "x":
                return "https://x.com/janedoe"
            return candidates[0]["url"]

        judge.pick.side_effect = _pick

        # Act
        changed = SourceEnrichmentService(
            web_search=web,
            profile_judge=judge,
        ).enrich_expert(expert)

        # Assert
        self.assertTrue(changed)
        expert.refresh_from_db()
        self.assertEqual(
            source_kinds_present(expert.sources),
            {"linkedin", "x", "google_scholar"},
        )
        self.assertEqual(web.search.call_count, 3)
        self.assertEqual(judge.pick.call_count, 3)
        x_urls = [
            item["url"]
            for item in expert.sources
            if isinstance(item, dict) and "x.com/" in item.get("url", "")
        ]
        self.assertEqual(x_urls, ["https://x.com/janedoe"])

    def test_enrich_experts_respects_web_search_budget(self):
        # Arrange
        experts = []
        for i in range(3):
            experts.append(
                Expert.objects.create(
                    email=f"e{i}@uni.edu",
                    first_name="Ada",
                    last_name=f"Lovelace{i}",
                    affiliation="Uni",
                    sources=[],
                )
            )
        web = MagicMock()
        web.configured = True
        web.search.return_value = [
            {
                "title": "Ada Lovelace0 | LinkedIn",
                "url": "https://www.linkedin.com/in/ada0",
                "description": "",
            }
        ]
        service = SourceEnrichmentService(
            web_search=web,
            profile_judge=_judge_picks_first(),
            max_web_searches=2,
        )

        # Act
        service.enrich_experts(experts)

        # Assert
        self.assertEqual(web.search.call_count, 2)

    def test_enrich_expert_noop_when_nothing_found(self):
        expert = Expert.objects.create(
            email="safe@uni.edu",
            first_name="Safe",
            last_name="User",
            sources=[{"text": "Faculty", "url": "https://uni.edu/safe"}],
        )
        service = SourceEnrichmentService(
            web_search=_empty_web_search(),
            profile_judge=MagicMock(),
        )
        self.assertFalse(service.enrich_expert(expert))
        expert.refresh_from_db()
        self.assertEqual(len(expert.sources), 1)
