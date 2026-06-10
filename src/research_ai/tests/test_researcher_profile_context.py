from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services.author_context import (
    build_author_context_snippet,
    build_author_context_text,
)
from research_ai.services.researcher_external_context import (
    build_researcher_external_context_for_author,
    fetch_openalex_author_record,
    format_openalex_author_record,
    format_orcid_works_payload,
)


class AuthorContextTests(SimpleTestCase):
    def test_build_author_context_text(self):
        self.assertEqual(build_author_context_text(None), "")
        author = SimpleNamespace(
            first_name="Jane",
            last_name="Doe",
            headline="Lab PI",
            university=SimpleNamespace(name="Example University", city="Boston"),
            country_code="US",
            description="Studies widgets.",
            orcid_id="https://orcid.org/0000-0002-1825-0097",
            openalex_ids=["https://openalex.org/A123"],
            h_index=12,
            i10_index=3,
            education=[{"school": "MIT"}],
            google_scholar="https://scholar.google.com/citations?user=x",
            linkedin=None,
        )
        text = build_author_context_text(author)
        self.assertIn("Jane Doe", text)
        self.assertIn("Example University", text)
        self.assertIn("Boston", text)
        self.assertIn("Studies widgets.", text)
        self.assertIn("ORCID", text)
        self.assertIn("OpenAlex author IDs", text)
        self.assertIn("h-index", text)
        self.assertIn("Education entries (count): 1", text)
        self.assertIn("Google Scholar", text)

    @patch("research_ai.services.author_context.Author.objects.filter")
    def test_build_author_context_snippet_resolves_linked_author(self, mock_filter):
        author = SimpleNamespace(
            first_name="Jane",
            last_name="Doe",
            headline="Lab PI",
            university=SimpleNamespace(name="Example University", city="Boston"),
            country_code="US",
            description="Studies widgets.",
            orcid_id="https://orcid.org/0000-0002-1825-0097",
            openalex_ids=["https://openalex.org/A123"],
            h_index=12,
            i10_index=3,
            education=[{"school": "MIT"}],
            google_scholar="https://scholar.google.com/citations?user=x",
            linkedin=None,
        )
        qs = MagicMock()
        qs.first.return_value = author
        mock_filter.return_value = qs
        ud = SimpleNamespace(
            created_by=SimpleNamespace(id=99, first_name="", last_name="")
        )
        text = build_author_context_snippet(ud)
        self.assertIn("Jane Doe", text)
        mock_filter.assert_called_once_with(user_id=99)

    def test_build_author_context_snippet_no_owner(self):
        ud = SimpleNamespace(created_by=None)
        self.assertEqual(build_author_context_snippet(ud), "")


class ResearcherExternalContextTests(SimpleTestCase):
    def test_format_openalex_author_record(self):
        self.assertEqual(format_openalex_author_record(None), "")
        self.assertEqual(format_openalex_author_record({}), "")
        rec = {
            "display_name": "Ada Lovelace",
            "orcid": "https://orcid.org/0000-0001-0000-0000",
            "summary_stats": {"h_index": 7, "i10_index": 2, "2yr_mean_citedness": 1.5},
            "works_count": 40,
            "cited_by_count": 500,
            "last_known_institution": {"display_name": "Royal Institution"},
            "affiliations": [
                {"institution": {"display_name": "Org One"}},
                {"institution": {"display_name": "Org Two"}},
            ],
            "topics": [{"display_name": "Computing"}],
            "x_concepts": [{"display_name": "Mathematics"}],
        }
        text = format_openalex_author_record(rec)
        self.assertIn("Ada Lovelace", text)
        self.assertIn("OpenAlex summary_stats", text)
        self.assertIn("works_count=40", text)
        self.assertIn("Royal Institution", text)
        self.assertIn("Org One", text)
        self.assertIn("Computing", text)
        self.assertIn("Mathematics", text)

    @patch("research_ai.services.researcher_external_context.OpenAlex")
    def test_fetch_openalex_prefers_orcid_and_skips_id_lookup(self, mock_oa_cls):
        client = MagicMock()
        mock_oa_cls.return_value = client
        client.get_author_via_orcid.return_value = {"display_name": "From ORCID"}

        rec = fetch_openalex_author_record(
            orcid_bare="0000-0001-2345-6789",
            openalex_author_ref="A999",
            client=client,
        )
        self.assertEqual(rec, {"display_name": "From ORCID"})
        client._get.assert_not_called()

    @patch("research_ai.services.researcher_external_context.OpenAlex")
    def test_fetch_openalex_by_author_id_when_no_orcid(self, mock_oa_cls):
        client = MagicMock()
        mock_oa_cls.return_value = client
        client._get.return_value = {"display_name": "From OA"}

        rec = fetch_openalex_author_record(
            orcid_bare=None,
            openalex_author_ref="A888",
            client=client,
        )
        self.assertEqual(rec, {"display_name": "From OA"})
        client._get.assert_called_once_with("authors/A888")

    def test_build_researcher_external_context_for_author_passes_ids(self):
        mod = "research_ai.services.researcher_external_context"
        author = SimpleNamespace(
            orcid_id="0000-0002-0000-0000",
            openalex_ids=["A5050505050"],
        )
        with patch(f"{mod}.build_researcher_external_context_text") as mock_build:
            mock_build.return_value = "ctx"
            out = build_researcher_external_context_for_author(
                author,
                client=MagicMock(),
            )
        self.assertEqual(out, "ctx")
        mock_build.assert_called_once()
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs["orcid_bare"], "0000-0002-0000-0000")
        self.assertEqual(kwargs["openalex_author_ref"], "A5050505050")

    def test_format_orcid_works_payload(self):
        self.assertEqual(format_orcid_works_payload(None), "")
        self.assertEqual(format_orcid_works_payload({}), "")
        payload = {
            "group": [
                {
                    "work-summary": [
                        {
                            "title": {"title": {"value": "Example Paper"}},
                            "publication-date": {"year": {"value": "2020"}},
                        }
                    ]
                }
            ]
        }
        text = format_orcid_works_payload(payload)
        self.assertIn("Example Paper", text)
        self.assertIn("2020", text)
