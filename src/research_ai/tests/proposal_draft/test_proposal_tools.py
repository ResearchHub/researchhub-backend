"""Unit tests for the proposal context + verification tools (no LLM, no network)."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from purchase.models import Grant
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.proposal_tools.context_tools import ProposalContextToolset
from research_ai.services.proposal_tools.verification_tools import (
    ProposalVerificationToolset,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_default_user


class _FakeOpenAlex:
    """Stand-in for ``utils.openalex.OpenAlex`` keyed by DOI."""

    def __init__(self, by_doi):
        self._by_doi = by_doi

    def get_work_by_doi(self, doi):
        return self._by_doi.get(doi)


class _FakeCrossref:
    """Minimal stand-in for ``utils.crossref.Crossref``."""

    def __init__(
        self, *, title=None, data_message=None, url=None, paper_publish_date=None
    ):
        self.title = title
        self.data_message = data_message or {}
        self.url = url
        self.paper_publish_date = paper_publish_date
        self.doi = None


def _openalex_work(title, authors, *, year=2020, doi="https://doi.org/10.1/x"):
    return {
        "display_name": title,
        "publication_year": year,
        "doi": doi,
        "id": "https://openalex.org/W1",
        "authorships": [{"author": {"display_name": name}} for name in authors],
    }


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

    def test_verify_citations_exact_on_match(self):
        # Arrange
        oa = _FakeOpenAlex(
            {"10.1/x": _openalex_work("Protein Folding Dynamics", ["Jane Smith"])}
        )
        tool = ProposalVerificationToolset(oa_client=oa)

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
            {"10.1/x": _openalex_work("Protein Folding Dynamics", ["Jane Smith"])}
        )
        tool = ProposalVerificationToolset(oa_client=oa)

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
            {"10.1/x": _openalex_work("Quantum Gravity in 2D", ["Alan Turing"])}
        )
        tool = ProposalVerificationToolset(oa_client=oa)

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

    def test_verify_citations_dead_on_none(self):
        # Arrange: neither OpenAlex nor Crossref resolve the DOI.
        oa = _FakeOpenAlex({})
        tool = ProposalVerificationToolset(
            oa_client=oa, crossref_factory=lambda doi: _FakeCrossref(title=None)
        )

        # Act
        out = tool.verify_citations(
            {"citations": [{"claim_id": "c1", "doi": "10.1/missing", "title": "X"}]}
        )

        # Assert
        result = out["results"][0]
        self.assertEqual(result["severity"], "dead")
        self.assertIsNone(result["resolved"])
        self.assertEqual(out["summary"]["dead"], 1)

    def test_verify_citations_falls_back_to_crossref(self):
        # Arrange: OpenAlex misses, Crossref resolves the record.
        oa = _FakeOpenAlex({})
        crossref = _FakeCrossref(
            title="Protein Folding Dynamics",
            data_message={"author": [{"given": "Jane", "family": "Smith"}]},
            url="https://doi.org/10.1/x",
        )
        tool = ProposalVerificationToolset(
            oa_client=oa, crossref_factory=lambda doi: crossref
        )

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
        self.assertEqual(
            out["results"][0]["resolved"]["title"], "Protein Folding Dynamics"
        )
