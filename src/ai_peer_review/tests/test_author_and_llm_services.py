from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from ai_peer_review.services.author_context import (
    build_author_context_snippet,
    build_author_context_text,
)
from ai_peer_review.services.bedrock_llm_service import (
    BEDROCK_MODEL_ID,
    BedrockLLMService,
)
from ai_peer_review.services.openai_web_context_service import (
    OPENAI_WEB_CONTEXT_MODEL,
    OpenAIReviewContextService,
)
from ai_peer_review.services.researcher_external_context import (
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

    @patch("ai_peer_review.services.author_context.Author.objects.filter")
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

    @patch("ai_peer_review.services.researcher_external_context.OpenAlex")
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

    @patch("ai_peer_review.services.researcher_external_context.OpenAlex")
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
        mod = "ai_peer_review.services.researcher_external_context"
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


class BedrockLLMServiceTests(SimpleTestCase):
    @patch("ai_peer_review.services.bedrock_llm_service.bedrock_runtime_client")
    def test_invoke_returns_joined_text(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "hello"}, {"text": " world"}],
                }
            }
        }

        svc = BedrockLLMService()
        out = svc.invoke("sys", "user", max_tokens=100, temperature=0.1)

        self.assertEqual(out, "hello world")
        mock_client.converse.assert_called_once()
        kwargs = mock_client.converse.call_args.kwargs
        self.assertEqual(kwargs["modelId"], BEDROCK_MODEL_ID)
        self.assertEqual(kwargs["system"], [{"text": "sys"}])
        self.assertEqual(kwargs["messages"][0]["role"], "user")
        self.assertEqual(kwargs["inferenceConfig"]["maxTokens"], 100)
        self.assertEqual(kwargs["inferenceConfig"]["temperature"], 0.1)

    @patch("ai_peer_review.services.bedrock_llm_service.bedrock_runtime_client")
    def test_invoke_omits_temperature_for_opus_4_7(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "x"}]}}
        }
        svc = BedrockLLMService()
        svc.model_id = "us.anthropic.claude-opus-4-7-20250514-v1:0"
        svc.invoke("s", "u", max_tokens=50, temperature=0.1)
        ic = mock_client.converse.call_args.kwargs["inferenceConfig"]
        self.assertEqual(ic, {"maxTokens": 50})

    @patch("ai_peer_review.services.bedrock_llm_service.bedrock_runtime_client")
    @patch("ai_peer_review.services.bedrock_llm_service.sentry.log_error")
    def test_invoke_raises_on_client_error(self, mock_sentry, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.converse.side_effect = RuntimeError("aws down")

        svc = BedrockLLMService()
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("s", "u")
        self.assertIn("Bedrock invoke failed", str(ctx.exception))
        mock_sentry.assert_called_once()


class OpenAIReviewContextServiceTests(SimpleTestCase):
    def test_build_user_prompt_truncates_long_proposal(self):
        svc = OpenAIReviewContextService()
        long_text = "x" * 30000
        prompt = svc.build_user_prompt(
            proposal_excerpt=long_text,
            researcher_display_name="Dr X",
            institutional_affiliation="Inst Y",
        )
        self.assertIn("[TRUNCATED]", prompt)
        self.assertIn("Dr X", prompt)
        self.assertIn("Inst Y", prompt)

    def test_missing_api_key_raises(self):
        with override_settings(OPENAI_API_KEY=""):
            svc = OpenAIReviewContextService()
        self.assertIsNone(svc._client)
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("a", "b")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("ai_peer_review.services.openai_web_context_service.OpenAI")
    def test_invoke_uses_responses_with_web_search(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = "  - bullet  "
        mock_client.responses.create.return_value = resp

        svc = OpenAIReviewContextService()
        self.assertEqual(svc.model_id, OPENAI_WEB_CONTEXT_MODEL)
        out = svc.invoke("sys", "user", max_tokens=512, temperature=0.0)
        self.assertEqual(out, "- bullet")
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(kwargs["max_output_tokens"], 512)
        mock_client.chat.completions.create.assert_not_called()

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("ai_peer_review.services.openai_web_context_service.OpenAI")
    def test_invoke_falls_back_to_chat(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("no responses")
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = "fallback"
        mock_client.chat.completions.create.return_value = completion

        svc = OpenAIReviewContextService()
        self.assertEqual(svc.invoke("s", "u"), "fallback")
        mock_client.chat.completions.create.assert_called_once()
