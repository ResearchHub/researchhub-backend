"""Unit tests for the expert-finder OpenAlex tool layer."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.constants import Region
from research_ai.services.expert_finder.openalex_tools import (
    ExpertFinderOpenAlexToolset,
)
from utils.openalex import normalize_openalex_id
from utils.tests.openalex_helpers import create_oa_author_record, create_oa_work


class ToolBuildTests(SimpleTestCase):
    def test_exposes_search_works_and_reused_author_tools(self):
        # Arrange / Act
        names = {
            tool.name
            for tool in ExpertFinderOpenAlexToolset(client=MagicMock()).build_tools()
        }
        # Assert
        self.assertEqual(
            names,
            {
                "search_works",
                "search_institutions",
                "search_authors",
                "get_author",
                "get_author_works",
            },
        )

    def test_no_terminal_tools(self):
        # Arrange / Act
        terminal = {
            tool.name
            for tool in ExpertFinderOpenAlexToolset(client=MagicMock()).build_tools()
            if tool.is_terminal
        }
        # Assert
        self.assertEqual(terminal, set())


def _oa_toolset(**kwargs) -> ExpertFinderOpenAlexToolset:
    """OpenAlex toolset that skips remote metadata email lookups in unit tests."""
    kwargs.setdefault("work_email_lookup_fn", lambda **_kw: [])
    return ExpertFinderOpenAlexToolset(**kwargs)


class SearchWorksTests(SimpleTestCase):
    def test_search_works_requires_query(self):
        # Arrange
        toolset = _oa_toolset(client=MagicMock()).as_toolset()
        # Act
        result, stop = toolset.dispatch("search_works", {"query": "  "})
        # Assert
        self.assertFalse(stop)
        self.assertIn("query is required", result["error"])

    def test_search_works_applies_default_year_window_and_grounds(self):
        # Arrange
        client = MagicMock()
        entity = create_oa_work("CRISPR paper", 2024, "first")
        entity["authorships"] = [
            {
                "author": {
                    "id": "https://openalex.org/A999",
                    "display_name": "Ada Expert",
                },
                "author_position": "first",
                "institutions": [{"display_name": "MIT"}],
            }
        ]
        client.get_works.return_value = ([entity], "cursor-2")
        provider = _oa_toolset(client=client)
        toolset = provider.as_toolset()
        expected_from = (date.today() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

        # Act
        result, stop = toolset.dispatch(
            "search_works", {"query": "CRISPR gene editing", "max_results": 10}
        )

        # Assert
        self.assertFalse(stop)
        client.get_works.assert_called_once_with(
            search="CRISPR gene editing",
            from_publication_date=expected_from,
            next_cursor="*",
            batch_size=10,
            exclude_openalex_ids=None,
        )
        self.assertEqual(result["from_publication_date"], expected_from)
        self.assertEqual(result["next_cursor"], "cursor-2")
        self.assertTrue(result["has_more"])
        self.assertNotIn("result_count_total", result)
        work = result["works"][0]
        self.assertEqual(work["title"], "CRISPR paper")
        self.assertEqual(work["authors"][0]["display_name"], "Ada Expert")
        self.assertEqual(work["authors"][0]["institutions"], ["MIT"])
        self.assertIn(work["source_url"], provider.returned_works)
        self.assertTrue(provider.has_returned_author("https://openalex.org/A999"))
        self.assertTrue(provider.has_returned_author("A999"))
        self.assertFalse(provider.has_returned_author("A000"))
        self.assertEqual(
            provider.work_ids_for_authors(["A999"]),
            [normalize_openalex_id(entity["id"])],
        )

    def test_search_works_honors_explicit_from_publication_date_and_cursor(self):
        # Arrange
        client = MagicMock()
        client.get_works.return_value = ([], None)
        toolset = _oa_toolset(client=client).as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "search_works",
            {
                "query": "mRNA vaccines",
                "from_publication_date": "2022-01-01",
                "cursor": "page-2",
                "max_results": 5,
            },
        )

        # Assert
        client.get_works.assert_called_once_with(
            search="mRNA vaccines",
            from_publication_date="2022-01-01",
            next_cursor="page-2",
            batch_size=5,
            exclude_openalex_ids=None,
        )
        self.assertEqual(result["from_publication_date"], "2022-01-01")
        self.assertFalse(result["has_more"])

    def test_search_works_keeps_first_last_and_trims_middle(self):
        # Arrange: 1 first + 9 middle + 1 last → keep first, last, and 2 middle.
        client = MagicMock()
        authorships = [
            {
                "author": {"id": "https://openalex.org/A1", "display_name": "First"},
                "author_position": "first",
            },
            *[
                {
                    "author": {
                        "id": f"https://openalex.org/AM{i}",
                        "display_name": f"Mid{i}",
                    },
                    "author_position": "middle",
                }
                for i in range(9)
            ],
            {
                "author": {"id": "https://openalex.org/A9", "display_name": "Last"},
                "author_position": "last",
            },
        ]
        entity = create_oa_work("Big Collab", 2023, "first")
        entity["authorships"] = authorships
        client.get_works.return_value = ([entity], None)
        provider = _oa_toolset(client=client)
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch("search_works", {"query": "collab"})

        # Assert
        authors = result["works"][0]["authors"]
        names = [a["display_name"] for a in authors]
        self.assertEqual(names[0], "First")
        self.assertEqual(names[-1], "Last")
        self.assertEqual(len(authors), 4)
        self.assertEqual(names[1:3], ["Mid0", "Mid1"])
        self.assertTrue(provider.has_returned_author("A1"))
        self.assertTrue(provider.has_returned_author("A9"))
        self.assertTrue(provider.has_returned_author("AM0"))
        self.assertFalse(provider.has_returned_author("AM2"))
        self.assertIn("batch", result)
        # Chase batch is easy-priority only (first/last medium); middle
        # coauthors without orcid/institution stay low and are not chased.
        self.assertEqual(result["batch"]["batch_authors"], 2)
        self.assertEqual(result["batch"]["required_chased"], 1)

    def test_search_works_attaches_metadata_email_and_easy_batch(self):
        # Arrange
        client = MagicMock()
        entity = create_oa_work("Corr paper", 2024, "first")
        entity["doi"] = "https://doi.org/10.1/test"
        entity["authorships"] = [
            {
                "author": {
                    "id": "https://openalex.org/A1",
                    "display_name": "Ada Expert",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                },
                "author_position": "first",
                "is_corresponding": True,
                "institutions": [{"display_name": "MIT", "country_code": "US"}],
                "raw_affiliation_strings": ["MIT; ada@mit.edu"],
            },
            {
                "author": {
                    "id": "https://openalex.org/A2",
                    "display_name": "Mid Nobody",
                },
                "author_position": "middle",
                "institutions": [],
            },
        ]

        def _lookup(*, doi, authorships):
            from research_ai.services.expert_finder.work_email_lookup import (
                emails_from_openalex_authorships,
            )

            return emails_from_openalex_authorships(authorships)

        client.get_works.return_value = ([entity], None)
        provider = ExpertFinderOpenAlexToolset(
            client=client,
            work_email_lookup_fn=_lookup,
        )
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch("search_works", {"query": "corr"})

        # Assert
        author = result["works"][0]["authors"][0]
        self.assertEqual(author["metadata_email"], "ada@mit.edu")
        self.assertEqual(author["chase_priority"], "high")
        self.assertNotIn("suggested_web_query", author)
        self.assertEqual(result["batch"]["batch_authors"], 1)

    def test_search_works_blocked_until_batch_chase_quota(self):
        # Arrange — page with 4 authors; need ceil(0.3*4)=2 chased before next page.
        client = MagicMock()
        entities = []
        for i in range(4):
            entity = create_oa_work(f"Paper {i}", 2024, "first")
            entity["id"] = f"https://openalex.org/W{i}"
            entity["authorships"] = [
                {
                    "author": {
                        "id": f"https://openalex.org/A{i}",
                        "display_name": f"Author {i}",
                    },
                    "author_position": "first",
                    "institutions": [{"display_name": "MIT"}],
                }
            ]
            entities.append(entity)
        client.get_works.return_value = (entities, "cursor-2")
        provider = _oa_toolset(client=client)
        toolset = provider.as_toolset()

        # Act
        first, _ = toolset.dispatch(
            "search_works", {"query": "topic", "max_results": 4}
        )
        blocked, _ = toolset.dispatch("search_works", {"query": "topic"})
        provider.mark_author_chased("A0")
        still_blocked, _ = toolset.dispatch("search_works", {"query": "topic"})
        provider.mark_author_chased("A1")
        client.get_works.return_value = ([], None)
        allowed, _ = toolset.dispatch("search_works", {"query": "topic"})

        # Assert
        self.assertEqual(first["batch"]["batch_authors"], 4)
        self.assertIn("Email-chase at least", blocked["error"])
        self.assertIn("Email-chase at least", still_blocked["error"])
        self.assertNotIn("error", allowed)
        self.assertEqual(client.get_works.call_count, 2)


class AuthorIdentityMatchTests(SimpleTestCase):
    def setUp(self):
        self.provider = ExpertFinderOpenAlexToolset(client=MagicMock())
        self.provider._record_author("https://openalex.org/A1", "Alice Smith")
        self.provider._record_author("https://openalex.org/A3", "Wei Li")

    def test_token_match_not_substring(self):
        # Arrange / Act / Assert
        self.assertTrue(
            self.provider.author_identity_matches(
                {
                    "openalex_author_id": "A1",
                    "first_name": "Alice",
                    "last_name": "Smith",
                }
            )
        )
        self.assertFalse(
            self.provider.author_identity_matches(
                {"openalex_author_id": "A1", "first_name": "Alice", "last_name": "Li"}
            )
        )
        self.assertFalse(
            self.provider.author_identity_matches(
                {"openalex_author_id": "A1", "first_name": "Bob", "last_name": "Smith"}
            )
        )
        self.assertTrue(
            self.provider.author_identity_matches(
                {"openalex_author_id": "A3", "first_name": "Wei", "last_name": "Li"}
            )
        )


class AuthorGroundingTests(SimpleTestCase):
    def test_get_author_records_returned_author_identity(self):
        # Arrange
        client = MagicMock()
        client.get_author.return_value = create_oa_author_record(
            id="https://openalex.org/A777"
        )
        provider = _oa_toolset(client=client)
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "get_author", {"openalex_author_id": "https://openalex.org/A777"}
        )

        # Assert
        self.assertEqual(result["openalex_author_id"], "https://openalex.org/A777")
        self.assertTrue(provider.has_returned_author("A777"))
        self.assertTrue(provider.returned_authors.get("a777"))

    def test_get_author_annotates_region_match(self):
        # Arrange
        client = MagicMock()
        client.get_author.return_value = create_oa_author_record(
            id="https://openalex.org/A777",
            last_known_institutions=[
                {"display_name": "MIT", "country_code": "US"},
            ],
        )
        provider = _oa_toolset(
            client=client, region_filter=Region.US, state_filter="Massachusetts"
        )
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "get_author", {"openalex_author_id": "https://openalex.org/A777"}
        )

        # Assert
        self.assertEqual(result["country_codes"], ["US"])
        self.assertTrue(result["matches_region"])
        self.assertFalse(result["matches_state"])
        self.assertIn("a777", provider.returned_author_records)

    def test_caches_affiliation_country_codes_when_last_known_empty(self):
        # Arrange: OpenAlex last_known is empty; geo lives on affiliations.
        client = MagicMock()
        client.get_author.return_value = create_oa_author_record(
            id="https://openalex.org/A777",
            last_known_institutions=[],
            affiliations=[
                {
                    "institution": {
                        "display_name": "MIT",
                        "country_code": "US",
                    }
                }
            ],
        )
        provider = _oa_toolset(client=client, region_filter=Region.US)
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "get_author", {"openalex_author_id": "https://openalex.org/A777"}
        )
        client.get_author.reset_mock()
        record = provider.resolve_author_record("https://openalex.org/A777")

        # Assert
        self.assertEqual(result["country_codes"], ["US"])
        self.assertTrue(result["matches_region"])
        self.assertEqual(record["affiliations"][0]["institution"]["country_code"], "US")
        client.get_author.assert_not_called()

    def test_fetches_author_when_compact_view_has_no_country_codes(self):
        # Arrange: name-only compact view would otherwise poison the cache.
        client = MagicMock()
        client.get_author.return_value = create_oa_author_record(
            id="https://openalex.org/A777",
            last_known_institutions=[],
            affiliations=[
                {
                    "institution": {
                        "display_name": "MIT",
                        "country_code": "US",
                    }
                }
            ],
        )
        provider = _oa_toolset(client=client, region_filter=Region.US)

        # Act
        provider._annotate_and_cache_author_view(
            {
                "openalex_author_id": "https://openalex.org/A777",
                "display_name": "Ada Expert",
                "institutions": ["MIT"],
                "last_known_institutions": [],
            }
        )

        # Assert
        client.get_author.assert_called_once()
        record = provider.resolve_author_record("A777")
        self.assertEqual(record["affiliations"][0]["institution"]["country_code"], "US")
        self.assertTrue(record.get("id"))

    def test_search_authors_records_candidate_ids(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record(id="https://openalex.org/A555")]
        }
        provider = _oa_toolset(client=client)
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch("search_authors", {"name": "Jane Doe"})

        # Assert
        self.assertEqual(
            result["results"][0]["openalex_author_id"], "https://openalex.org/A555"
        )
        self.assertTrue(provider.has_returned_author("A555"))

    def test_get_author_works_shares_returned_works_without_grounding_input_id(self):
        # Arrange: listing works must not treat the input author id as proven.
        client = MagicMock()
        client.get_works.return_value = (
            [create_oa_work("Lead Paper", 2024, "first")],
            None,
        )
        provider = _oa_toolset(client=client)
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "get_author_works", {"openalex_author_id": "https://openalex.org/A123"}
        )

        # Assert
        url = result["works"][0]["source_url"]
        self.assertIn(url, provider.returned_works)
        self.assertFalse(provider.has_returned_author("A123"))


class ExcludeWorkIdsTests(SimpleTestCase):
    def test_search_works_passes_exclude_ids_to_client(self):
        # Arrange
        client = MagicMock()
        client.get_works.return_value = ([], None)
        toolset = _oa_toolset(
            client=client,
            exclude_work_ids=["https://openalex.org/W111", "W222"],
        ).as_toolset()

        # Act
        toolset.dispatch("search_works", {"query": "CRISPR", "max_results": 5})

        # Assert
        kwargs = client.get_works.call_args.kwargs
        self.assertEqual(kwargs["exclude_openalex_ids"], ["W111", "W222"])
        self.assertNotIn("include_meta", kwargs)

    def test_search_works_filters_excluded_ids_from_payload(self):
        # Arrange
        client = MagicMock()
        keep = create_oa_work("Keep", 2024, "first")
        keep["id"] = "https://openalex.org/WKEEP"
        drop = create_oa_work("Drop", 2024, "first")
        drop["id"] = "https://openalex.org/WDROP"
        client.get_works.return_value = ([keep, drop], None)
        provider = _oa_toolset(
            client=client,
            exclude_work_ids=["WDROP"],
        )
        toolset = provider.as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "search_works", {"query": "topic", "max_results": 10}
        )

        # Assert
        titles = [w["title"] for w in result["works"]]
        self.assertEqual(titles, ["Keep"])
        self.assertEqual(provider.collected_work_ids(), ["WKEEP"])
