"""Unit tests for the proposal web-search tool (no network, fake client)."""

from unittest import TestCase

from research_ai.services.proposal_tools import ProposalWebSearchToolset


class _FakeSearchClient:
    """Search client stand-in: configurable, records queries, returns fixtures."""

    def __init__(self, results, *, configured=True):
        self._results = results
        self.configured = configured
        self.queries = []

    def search(self, query, *, count=5):
        self.queries.append(query)
        return list(self._results)


def _tool(toolset):
    (tool,) = toolset.build_tools()
    return tool


class ProposalWebSearchToolsetTests(TestCase):
    def test_returns_results_and_records_provenance(self):
        # Arrange
        provenance = set()
        results = [
            {
                "title": "T",
                "url": "https://example.org/a",
                "description": "d",
                "age": "",
            }
        ]
        toolset = ProposalWebSearchToolset(
            client=_FakeSearchClient(results), provenance=provenance
        )

        # Act
        out = _tool(toolset).handler({"query": "public MS dataset accession"})

        # Assert: results are passed through and the URL is recorded in provenance.
        self.assertEqual(out["results"], results)
        self.assertIn("https://example.org/a", provenance)

    def test_missing_query_is_an_error(self):
        # Arrange
        toolset = ProposalWebSearchToolset(client=_FakeSearchClient([]))

        # Act / Assert
        self.assertIn("error", _tool(toolset).handler({"query": "  "}))

    def test_unconfigured_client_returns_explanatory_error(self):
        # Arrange: client present but without an API key.
        client = _FakeSearchClient([], configured=False)
        toolset = ProposalWebSearchToolset(client=client)

        # Act
        out = _tool(toolset).handler({"query": "anything"})

        # Assert: an explanatory error, and no search was attempted.
        self.assertIn("not configured", out["error"])
        self.assertEqual(client.queries, [])

    def test_search_budget_is_capped(self):
        # Arrange: a 2-search budget against an always-answering client.
        client = _FakeSearchClient(
            [{"title": "T", "url": "https://e/x", "description": "", "age": ""}]
        )
        toolset = ProposalWebSearchToolset(client=client, max_searches=2)
        tool = _tool(toolset)

        # Act: three calls; the third should be refused.
        first = tool.handler({"query": "q1"})
        second = tool.handler({"query": "q2"})
        third = tool.handler({"query": "q3"})

        # Assert: two searches ran, the third was budget-refused.
        self.assertIn("results", first)
        self.assertIn("results", second)
        self.assertIn("error", third)
        self.assertIn("budget exhausted", third["error"])
        self.assertEqual(client.queries, ["q1", "q2"])
