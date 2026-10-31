"""Unit tests for the proposal context + verification tools (no LLM, no network)."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from purchase.models import Grant
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.citation_tools import CitationToolset
from research_ai.services.proposal_draft.tools.context_tools import (
    ProposalContextToolset,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_default_user


class _FakeOpenAlex:
    """Stand-in for ``utils.openalex.OpenAlex`` keyed by DOI."""

    def __init__(self, by_doi, *, works_by_query=None, semantic_by_query=None, fail=()):
        self._by_doi = by_doi
        self._works_by_query = works_by_query or {}
        # Semantic rankings default to the keyword ones.
        self._semantic_by_query = semantic_by_query
        self._fail = set(fail)  # "keyword" and/or "semantic"
        self.calls = []

    def get_work_by_doi(self, doi):
        return self._by_doi.get(doi)

    def search_works(self, query, per_page=5, *, semantic=False, filters=None):
        mode = "semantic" if semantic else "keyword"
        self.calls.append({"query": query, "mode": mode, "filters": filters or {}})
        if mode in self._fail:
            raise ConnectionError("OpenAlex unavailable")
        by_query = self._works_by_query
        if semantic and self._semantic_by_query is not None:
            by_query = self._semantic_by_query
        return by_query.get(query, [])[:per_page]

    def call(self, mode):
        return next(c for c in self.calls if c["mode"] == mode)


def _build_openalex_work(
    title,
    authors,
    *,
    year=2020,
    doi="https://doi.org/10.1/x",
    venue=None,
    work_id=None,
    abstract=None,
):
    work = {
        "display_name": title,
        "publication_year": year,
        "doi": doi,
        "id": work_id or f"https://openalex.org/W-{title}-{year}-{doi}",
        "authorships": [{"author": {"display_name": name}} for name in authors],
        "primary_location": {"source": {"display_name": venue}},
    }
    if abstract is not None:
        inverted = {}
        for position, word in enumerate(abstract.split()):
            inverted.setdefault(word, []).append(position)
        work["abstract_inverted_index"] = inverted
    return work


class ProposalToolsTestCase(TestCase):
    def setUp(self):
        # Arrange (shared fixtures): user, GRANT post + Grant, Expert + search.
        self.user = create_random_default_user("proposer")
        self.post = create_post(
            created_by=self.user,
            document_type=GRANT,
            renderable_text="Full RFP body: fund work on protein folding.",
        )
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            short_title="AI Healthcare RFP",
            description="Research grant for AI applications in healthcare",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )
        self.expert = Expert.objects.create(
            email="jane@example.edu",
            first_name="Jane",
            last_name="Smith",
            profile={
                "resolution": {"openalex_author_id": "A1", "confidence": 0.9},
                "works": [
                    {
                        "title": "Folding",
                        "source_url": "https://doi.org/10.1/a",
                        "pdf_url": "https://example.edu/a.pdf",
                    },
                    {
                        "title": "Misfolding",
                        "source_url": "https://doi.org/10.1/b",
                        "pdf_url": "",
                    },
                ],
            },
        )
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )

    # -- context tools ----------------------------------------------------

    def test_get_rfp_context_returns_text_and_structured_fields(self):
        # Arrange
        toolset = ProposalContextToolset(self.search_expert)
        get_rfp = toolset.as_toolset().get("get_rfp_context")

        # Act
        result = get_rfp.handler({})

        # Assert
        self.assertIn("Research grant for AI applications", result["rfp_text"])
        self.assertIn("AI Healthcare RFP", result["rfp_text"])
        self.assertEqual(result["amount"], "50000.00")
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["organization"], "National Science Foundation")
        self.assertEqual(result["short_title"], "AI Healthcare RFP")
        self.assertIsNotNone(result["end_date"])

    def test_get_rfp_context_errors_when_no_grant(self):
        # Arrange: a search whose document has no grant.
        plain_post = create_post(created_by=self.user)
        search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document=plain_post.unified_document,
            query="q",
        )
        se = SearchExpert.objects.create(expert_search=search, expert=self.expert)

        # Act
        result = ProposalContextToolset(se)._get_rfp_context({})

        # Assert
        self.assertIn("error", result)

    def test_get_researcher_profile_returns_profile_and_populates_provenance(self):
        # Arrange
        provenance: set[str] = set()
        toolset = ProposalContextToolset(self.search_expert, provenance=provenance)
        get_profile = toolset.as_toolset().get("get_researcher_profile")

        # Act
        result = get_profile.handler({})

        # Assert
        self.assertEqual(result["resolution"]["openalex_author_id"], "A1")
        self.assertEqual(
            provenance,
            {
                "https://doi.org/10.1/a",
                "https://example.edu/a.pdf",
                "https://doi.org/10.1/b",
            },
        )

    # -- verification tool ------------------------------------------------

    # -- search_works -----------------------------------------------------

    def test_search_works_returns_grounded_candidates(self):
        # Arrange: a title query resolves to a real DOI-bearing record.
        oa = _FakeOpenAlex(
            {},
            works_by_query={
                "Pericytes Stimulate Oligodendrocyte Differentiation": [
                    _build_openalex_work(
                        "Pericytes Stimulate Oligodendrocyte Differentiation",
                        ["De La Fuente"],
                        doi="https://doi.org/10.1016/j.celrep.2017.08.007",
                        venue="Cell Reports",
                    )
                ]
            },
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works(
            {"title": "Pericytes Stimulate Oligodendrocyte Differentiation"}
        )

        # Assert: the resolved DOI comes back as source_url, not invented.
        self.assertEqual(len(out["results"]), 1)
        result = out["results"][0]
        self.assertEqual(
            result["source_url"], "https://doi.org/10.1016/j.celrep.2017.08.007"
        )
        self.assertEqual(result["authors"], ["De La Fuente"])
        self.assertEqual(result["year"], 2020)
        self.assertEqual(result["venue"], "Cell Reports")

    def test_search_works_requires_title(self):
        # Arrange
        tool = CitationToolset(oa_client=_FakeOpenAlex({}))

        # Act
        out = tool.search_works({"title": "  "})

        # Assert
        self.assertIn("error", out)

    def test_search_works_empty_when_no_matches(self):
        # Arrange: the client returns nothing for an unknown query.
        tool = CitationToolset(oa_client=_FakeOpenAlex({}))

        # Act
        out = tool.search_works({"title": "a paper that does not exist"})

        # Assert
        self.assertEqual(out["results"], [])

    def test_search_works_passes_author_and_years_as_filters(self):
        # Arrange
        oa = _FakeOpenAlex({})
        tool = CitationToolset(oa_client=oa)

        # Act
        tool.search_works(
            {
                "title": "Reporting of noninferiority trials",
                "author": "Piaggio, G.",
                "year_from": 2012,
                "year_to": "2012",
            }
        )

        # Assert: the query is the title alone; author and year become filters
        # (a year of slack either side, for online-first dating), and the author
        # filter goes to keyword search only (semantic rejects it).
        keyword, semantic = oa.call("keyword"), oa.call("semantic")
        self.assertEqual(keyword["query"], "Reporting of noninferiority trials")
        self.assertEqual(semantic["query"], "Reporting of noninferiority trials")
        self.assertEqual(keyword["filters"]["publication_year"], "2011-2013")
        self.assertEqual(semantic["filters"]["publication_year"], "2011-2013")
        self.assertEqual(keyword["filters"]["raw_author_name.search"], "Piaggio G.")
        self.assertNotIn("raw_author_name.search", semantic["filters"])

    def test_search_works_open_ended_year_bounds(self):
        # Arrange
        oa = _FakeOpenAlex({})
        tool = CitationToolset(oa_client=oa)

        # Act
        tool.search_works({"title": "CRISPR base editing", "year_from": 2020})
        tool.search_works({"title": "CRISPR base editing", "year_to": 2015})
        tool.search_works({"title": "CRISPR base editing", "year_to": "soon"})

        # Assert
        years = [c["filters"].get("publication_year") for c in oa.calls[::2]]
        self.assertEqual(years, [">2018", "<2017", None])

    def test_search_works_trims_long_author_lists(self):
        # Arrange
        query = "ARRIVE guidelines"
        authors = [f"Author {n}" for n in range(30)]
        oa = _FakeOpenAlex(
            {}, works_by_query={query: [_build_openalex_work(query, authors)]}
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": query})

        # Assert: names are trimmed and the count is kept.
        result = out["results"][0]
        self.assertEqual(result["authors"], authors[:6])
        self.assertEqual(result["author_count"], 30)

    def test_search_works_fuses_keyword_and_semantic_rankings(self):
        # Arrange: one work in both rankings, one in each alone.
        both = _build_openalex_work("Stereotactic robot accuracy", ["Li"])
        keyword_only = _build_openalex_work(
            "Robotic neurosurgery review", ["Kim"], doi="https://doi.org/10.1/k"
        )
        semantic_only = _build_openalex_work(
            "Phantom validation of a neurosurgical robot",
            ["Ng"],
            doi="https://doi.org/10.1/s",
        )
        query = "robotic stereotaxic surgery accuracy brain phantom"
        oa = _FakeOpenAlex(
            {},
            works_by_query={query: [keyword_only, both]},
            semantic_by_query={query: [semantic_only, both]},
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": query})

        # Assert: agreement between the two searches ranks first, and works
        # only semantic search found still come back.
        titles = [r["title"] for r in out["results"]]
        self.assertEqual(titles[0], "Stereotactic robot accuracy")
        self.assertCountEqual(
            titles,
            [
                "Stereotactic robot accuracy",
                "Robotic neurosurgery review",
                "Phantom validation of a neurosurgical robot",
            ],
        )

    def test_search_works_ranks_exact_title_and_author_first(self):
        # Arrange: semantic search agrees on a related paper; keyword search
        # alone has the exact title.
        title = "Transancestral mapping and genetic load in systemic lupus"
        related = _build_openalex_work(
            "Genetics of lupus across ancestries",
            ["Other"],
            doi="https://doi.org/10.1/r",
        )
        exact = _build_openalex_work(title, ["Langefeld"], year=2017)
        oa = _FakeOpenAlex(
            {},
            works_by_query={title: [related, exact]},
            semantic_by_query={title: [related]},
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": title, "author": "Langefeld"})

        # Assert
        self.assertEqual(out["results"][0]["title"], title)

    def test_search_works_drops_works_without_doi_and_dedupes_reprints(self):
        # Arrange: the same guideline reprinted in two journals, an older
        # edition with the same title, and a semantic hit with no DOI.
        title = "The ARRIVE guidelines 2.0"
        reprint_a = _build_openalex_work(
            title, ["Percie du Sert"], doi="https://doi.org/10.1/a"
        )
        reprint_b = _build_openalex_work(
            title, ["Percie du Sert"], doi="https://doi.org/10.1/b"
        )
        older = _build_openalex_work(
            title, ["Kilkenny"], year=2010, doi="https://doi.org/10.1/old"
        )
        no_doi = _build_openalex_work("ARRIVE thesis", ["Student"], doi=None)
        oa = _FakeOpenAlex(
            {},
            works_by_query={title: [reprint_a, reprint_b, older]},
            semantic_by_query={title: [no_doi, reprint_b]},
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": title})

        # Assert
        results = [(r["title"], r["year"]) for r in out["results"]]
        self.assertEqual(results, [(title, 2020), (title, 2010)])

    def test_search_works_ranks_replies_and_meeting_abstracts_last(self):
        # Arrange
        query = "new cutoffs adrenal insufficiency ACTH stimulation"
        letter = _build_openalex_work(
            "Letter to the Editor: new cutoffs", ["A"], doi="https://doi.org/10.1/l"
        )
        meeting = _build_openalex_work(
            "SUN-477 Cortisol cutoffs", ["B"], doi="https://doi.org/10.1/m"
        )
        paper = _build_openalex_work(
            "Cortisol assay cutoffs after ACTH", ["C"], doi="https://doi.org/10.1/p"
        )
        oa = _FakeOpenAlex({}, works_by_query={query: [letter, meeting, paper]})
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": query})

        # Assert
        self.assertEqual(
            out["results"][0]["title"], "Cortisol assay cutoffs after ACTH"
        )
        self.assertEqual(len(out["results"]), 3)

    def test_search_works_survives_one_search_failing(self):
        # Arrange
        query = "waking salivary cortisone"
        work = _build_openalex_work("Home waking salivary cortisone", ["Debono"])
        oa = _FakeOpenAlex({}, works_by_query={query: [work]}, fail={"semantic"})
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": query})

        # Assert
        self.assertEqual(
            [r["title"] for r in out["results"]], ["Home waking salivary cortisone"]
        )

    def test_search_works_includes_abstract_excerpt(self):
        # Arrange
        query = "myotube atrophy"
        long_abstract = "word " * 200
        short = _build_openalex_work(
            "Short",
            ["A"],
            doi="https://doi.org/10.1/s",
            abstract="Cachexia drives atrophy.",
        )
        long = _build_openalex_work(
            "Long", ["B"], doi="https://doi.org/10.1/l", abstract=long_abstract
        )
        bare = _build_openalex_work("Bare", ["C"], doi="https://doi.org/10.1/b")
        oa = _FakeOpenAlex({}, works_by_query={query: [short, long, bare]})
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.search_works({"title": query})

        # Assert
        by_title = {r["title"]: r["abstract"] for r in out["results"]}
        self.assertEqual(by_title["Short"], "Cachexia drives atrophy.")
        self.assertTrue(by_title["Long"].endswith(" ..."))
        self.assertLessEqual(len(by_title["Long"]), 404)
        self.assertEqual(by_title["Bare"], "")

    def test_verify_citations_exact_on_match(self):
        # Arrange
        oa = _FakeOpenAlex(
            {"10.1/x": _build_openalex_work("Protein Folding Dynamics", ["Jane Smith"])}
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.verify_citations(
            {
                "citations": [
                    {
                        "claim_id": "c1",
                        "doi": "10.1/x",
                        "title": "Protein Folding Dynamics",
                        "authors": ["Jane Smith"],
                    }
                ]
            }
        )

        # Assert
        self.assertEqual(out["results"][0]["severity"], "exact")
        self.assertNotIn("correction", out["results"][0])
        self.assertEqual(out["summary"], {"dead": 0, "major": 0, "minor": 0})

    def test_verify_citations_minor_drift_returns_correction(self):
        # Arrange: same paper, drifted title + author surname intact.
        oa = _FakeOpenAlex(
            {"10.1/x": _build_openalex_work("Protein Folding Dynamics", ["Jane Smith"])}
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.verify_citations(
            {
                "citations": [
                    {
                        "claim_id": "c1",
                        "doi": "10.1/x",
                        "title": "Protein Folding",
                        "authors": ["Jane Smith"],
                    }
                ]
            }
        )

        # Assert
        result = out["results"][0]
        self.assertEqual(result["severity"], "minor_drift")
        self.assertEqual(result["correction"]["title"], "Protein Folding Dynamics")
        self.assertEqual(out["summary"]["minor"], 1)

    def test_verify_citations_major_fabrication_on_title_mismatch(self):
        # Arrange: DOI resolves, but to a completely different paper.
        oa = _FakeOpenAlex(
            {"10.1/x": _build_openalex_work("Quantum Gravity in 2D", ["Alan Turing"])}
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.verify_citations(
            {
                "citations": [
                    {
                        "claim_id": "c1",
                        "doi": "10.1/x",
                        "title": "Protein Folding Dynamics",
                        "authors": ["Jane Smith"],
                    }
                ]
            }
        )

        # Assert
        result = out["results"][0]
        self.assertEqual(result["severity"], "major_fabrication")
        self.assertEqual(out["summary"]["major"], 1)

    def test_verify_citations_major_fabrication_on_author_mismatch(self):
        # Arrange: DOI/title resolve, but the claimed author contradicts OpenAlex.
        oa = _FakeOpenAlex(
            {"10.1/x": _build_openalex_work("Protein Folding Dynamics", ["Jane Smith"])}
        )
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.verify_citations(
            {
                "citations": [
                    {
                        "claim_id": "c1",
                        "doi": "10.1/x",
                        "title": "Protein Folding",
                        "authors": ["Alan Turing"],
                    }
                ]
            }
        )

        # Assert
        result = out["results"][0]
        self.assertEqual(result["severity"], "major_fabrication")
        self.assertNotIn("correction", result)
        self.assertEqual(out["summary"]["major"], 1)

    def test_verify_citations_dead_when_openalex_misses(self):
        # Arrange: OpenAlex does not resolve the DOI.
        oa = _FakeOpenAlex({})
        tool = CitationToolset(oa_client=oa)

        # Act
        out = tool.verify_citations(
            {"citations": [{"claim_id": "c1", "doi": "10.1/missing", "title": "X"}]}
        )

        # Assert
        result = out["results"][0]
        self.assertEqual(result["severity"], "dead")
        self.assertIsNone(result["resolved"])
        self.assertEqual(out["summary"]["dead"], 1)
