from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import EmailTemplate
from research_ai.services.email_generator_service import (
    _build_signature_block,
    _parse_subject_and_body,
    _replace_placeholders,
    _strip_existing_signature,
    _strip_markdown,
    generate_expert_email,
    normalize_llm_text_for_subject,
    normalize_llm_text_to_html,
)
from research_ai.services.expert_search_email_document_context import (
    ExpertSearchEmailDocumentContext,
)


class NormalizeLlmTextToHtmlTests(TestCase):
    def test_empty_or_none_passthrough(self):
        self.assertEqual(normalize_llm_text_to_html(""), "")
        self.assertEqual(normalize_llm_text_to_html(None), None)

    def test_each_newline_is_its_own_paragraph(self):
        self.assertEqual(
            normalize_llm_text_to_html("Line one\nLine two"),
            "<p>Line one</p><p>Line two</p>",
        )

    def test_blank_lines_become_empty_paragraphs(self):
        self.assertEqual(
            normalize_llm_text_to_html("A\n\nB"),
            "<p>A</p><p></p><p>B</p>",
        )

    def test_multiple_blank_lines(self):
        self.assertEqual(
            normalize_llm_text_to_html("A\n\n\nB"),
            "<p>A</p><p></p><p></p><p>B</p>",
        )

    def test_literal_backslash_n_normalized(self):
        self.assertEqual(
            normalize_llm_text_to_html("Hi\\n\\nThere"),
            "<p>Hi</p><p></p><p>There</p>",
        )

    def test_mixed_literal_and_real_newlines(self):
        self.assertEqual(
            normalize_llm_text_to_html("One\nTwo\\n\nThree"),
            "<p>One</p><p>Two</p><p></p><p>Three</p>",
        )


class NormalizeLlmTextForSubjectTests(TestCase):
    def test_empty_or_none_passthrough(self):
        self.assertEqual(normalize_llm_text_for_subject(""), "")
        self.assertEqual(normalize_llm_text_for_subject(None), None)

    def test_newlines_collapsed_to_spaces(self):
        self.assertEqual(
            normalize_llm_text_for_subject("Line one\nLine two"),
            "Line one Line two",
        )

    def test_literal_backslash_n_collapsed(self):
        self.assertEqual(
            normalize_llm_text_for_subject("Hi\\n\\nThere"),
            "Hi There",
        )


class StripMarkdownTests(TestCase):
    def test_strips_bold_double_asterisk(self):
        self.assertEqual(_strip_markdown("Hello **bold** world"), "Hello bold world")

    def test_strips_bold_double_underscore(self):
        self.assertEqual(_strip_markdown("Hello __bold__ world"), "Hello bold world")

    def test_strips_italic_single_asterisk(self):
        self.assertEqual(_strip_markdown("Hello *italic* world"), "Hello italic world")

    def test_strips_italic_single_underscore(self):
        self.assertEqual(_strip_markdown("Hello _italic_ world"), "Hello italic world")

    def test_strips_inline_code(self):
        self.assertEqual(_strip_markdown("See `code` here"), "See code here")

    def test_strips_markdown_links_keeps_text(self):
        self.assertEqual(
            _strip_markdown("See [link text](https://example.com) here"),
            "See link text here",
        )

    def test_combined_markdown(self):
        text = "**Bold** and *italic* with `code` and [click](https://x.com)."
        self.assertEqual(
            _strip_markdown(text),
            "Bold and italic with code and click.",
        )


class StripExistingSignatureTests(TestCase):
    def test_cuts_at_separator_in_second_half(self):
        text = (
            "First paragraph.\n\nSecond paragraph.\n\n---\n\n[Your Name]\n[Institution]"
        )
        result = _strip_existing_signature(text, None)
        self.assertNotIn("---", result)
        self.assertIn("Second paragraph", result)
        self.assertNotIn("[Your Name]", result)

    def test_keeps_separator_in_first_half(self):
        text = "Intro\n\n---\n\nBody text here."
        result = _strip_existing_signature(text, None)
        self.assertIn("---", result)
        self.assertIn("Body text here", result)

    def test_removes_trailing_closing_phrase_and_signature(self):
        text = "Email body here.\n\nBest regards,\n\n[Your Name]\n[Institution]"
        result = _strip_existing_signature(text, None)
        self.assertEqual(result, "Email body here.")
        self.assertNotIn("Best regards", result)

    def test_uses_last_closing_phrase(self):
        text = "Body.\n\nThanks,\n\nJane\n\nBest regards,\n\n[Your Name]"
        result = _strip_existing_signature(text, None)
        self.assertIn("Body.", result)
        self.assertIn("Thanks", result)
        self.assertNotIn("Best regards", result)
        self.assertNotIn("[Your Name]", result)

    def test_strips_trailing_lines_matching_template_data(self):
        text = "Body paragraph.\n\nJane Doe\nProf\nMIT"
        template_data = {"name": "Jane Doe", "title": "Prof", "institution": "MIT"}
        result = _strip_existing_signature(text, template_data)
        self.assertEqual(result, "Body paragraph.")

    def test_no_closing_phrase_returns_unchanged(self):
        text = "No signature here, just body."
        result = _strip_existing_signature(text, None)
        self.assertEqual(result, "No signature here, just body.")


class ReplacePlaceholdersTests(TestCase):
    def test_replaces_name_placeholders(self):
        text = "Signed, [Your Name]"
        data = {
            "name": "Jane Doe",
            "title": "",
            "institution": "",
            "email": "",
            "phone": "",
            "website": "",
        }
        self.assertEqual(_replace_placeholders(text, data), "Signed, Jane Doe")

    def test_replaces_title_and_institution(self):
        text = "[Your Title] at [Institution]"
        data = {
            "name": "",
            "title": "Prof",
            "institution": "MIT",
            "email": "",
            "phone": "",
            "website": "",
        }
        self.assertEqual(_replace_placeholders(text, data), "Prof at MIT")

    def test_replaces_email_phone_website(self):
        text = "Contact: [Email] [Phone] [Website]"
        data = {
            "name": "",
            "title": "",
            "institution": "",
            "email": "j@x.com",
            "phone": "555",
            "website": "https://x.com",
        }
        self.assertEqual(
            _replace_placeholders(text, data), "Contact: j@x.com 555 https://x.com"
        )

    def test_empty_value_does_not_replace(self):
        text = "[Your Name]"
        data = {
            "name": "",
            "title": "",
            "institution": "",
            "email": "",
            "phone": "",
            "website": "",
        }
        self.assertEqual(_replace_placeholders(text, data), "[Your Name]")


class BuildSignatureBlockTests(TestCase):
    def test_empty_template_data_returns_empty_string(self):
        self.assertEqual(_build_signature_block({}), "")

    def test_all_empty_values_returns_empty_string(self):
        data = {
            "name": "",
            "title": "",
            "institution": "",
            "email": "",
            "phone": "",
            "website": "",
        }
        self.assertEqual(_build_signature_block(data), "")

    def test_builds_signature_with_all_parts(self):
        data = {
            "name": "Jane",
            "title": "Prof",
            "institution": "MIT",
            "email": "j@mit.edu",
            "phone": "",
            "website": "",
        }
        result = _build_signature_block(data)
        self.assertTrue(result.startswith("\n\nBest regards,\n\n"))
        self.assertIn("Jane", result)
        self.assertIn("Prof", result)
        self.assertIn("MIT", result)
        self.assertIn("j@mit.edu", result)


class ParseSubjectAndBodyTests(TestCase):
    def test_parses_subject_line_and_body(self):
        text = "Subject: Collaboration request\n\nHi,\n\nThis is the body."
        subject, body = _parse_subject_and_body(text)
        self.assertEqual(subject, "Collaboration request")
        self.assertEqual(body, "Hi,\n\nThis is the body.")

    def test_case_insensitive_subject(self):
        text = "SUBJECT: Hello\n\nBody here."
        subject, body = _parse_subject_and_body(text)
        self.assertEqual(subject, "Hello")
        self.assertEqual(body, "Body here.")

    def test_no_subject_line_returns_empty_subject(self):
        text = "Just body text, no Subject: line."
        subject, body = _parse_subject_and_body(text)
        self.assertEqual(subject, "")
        self.assertEqual(body, "Just body text, no Subject: line.")


class GenerateExpertEmailTests(TestCase):
    @patch("research_ai.services.email_generator_service.BedrockLLMService")
    @patch("research_ai.services.email_generator_service.build_email_prompt")
    def test_returns_subject_and_body_from_llm_output(
        self, mock_build_prompt, mock_bedrock_class
    ):
        mock_build_prompt.return_value = "user prompt"
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = (
            "Subject: Invitation to collaborate\n\n"
            "Dear Dr. Smith,\n\n"
            "We would like to invite you.\n\n"
            "Best regards,\n\n"
            "[Your Name]"
        )
        mock_bedrock_class.return_value = mock_llm

        subject, body = generate_expert_email(
            resolved_expert={
                "honorific": "Dr",
                "last_name": "Smith",
                "academic_title": "Professor",
            },
            template="collaboration",
        )

        self.assertEqual(subject, "Invitation to collaborate")
        self.assertIn("Dear Dr. Smith", body)
        mock_llm.invoke.assert_called_once()

    @patch("research_ai.services.email_generator_service.BedrockLLMService")
    @patch("research_ai.services.email_generator_service.build_email_prompt")
    def test_post_processes_with_user_signature(
        self, mock_build_prompt, mock_bedrock_class
    ):
        mock_build_prompt.return_value = "user prompt"
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = (
            "Subject: Hello\n\n"
            "Body with [Your Name] and [Institution].\n\n"
            "Best regards,\n\n"
            "[Your Name]\n"
            "[Institution]"
        )
        mock_bedrock_class.return_value = mock_llm

        user = SimpleNamespace(
            first_name="Jane",
            last_name="Doe",
            email="jane@mit.edu",
            author_profile=SimpleNamespace(headline=""),
            organization=None,
        )

        subject, body = generate_expert_email(
            resolved_expert={"first_name": "Expert"},
            template="collaboration",
            user=user,
        )

        self.assertEqual(subject, "Hello")
        self.assertIn("Jane Doe", body)
        self.assertIn("jane@mit.edu", body)
        self.assertNotIn("[Your Name]", body)
        self.assertNotIn("[Institution]", body)

    @patch(
        "research_ai.services.email_generator_service.resolve_expert_search_email_document_context"
    )
    @patch("research_ai.services.email_generator_service.get_email_template")
    def test_fixed_template_uses_resolver_rfp_context(
        self, mock_get_template, mock_resolve_doc
    ):
        rfp_context = {
            "amount": "$10K",
            "deadline": "March 1",
            "title": "Test RFP",
            "url": "https://x.com/g",
            "blurb": "RFP description",
        }
        mock_resolve_doc.return_value = ExpertSearchEmailDocumentContext(
            rfp_context_dict=rfp_context,
            proposal_context_dict=None,
            generic_work_context_dict=None,
        )
        expert_search = MagicMock()
        user = MagicMock()
        et = MagicMock(spec=EmailTemplate)
        et.email_subject = "Subject: {{rfp.title}}"
        et.email_body = "Hi {{expert.name}}, see {{rfp.amount}} and {{rfp.deadline}}."
        mock_get_template.return_value = et
        subject, body = generate_expert_email(
            resolved_expert={"honorific": "Dr", "last_name": "X"},
            template=None,
            expert_search=expert_search,
            template_id=1,
            user=user,
        )
        mock_get_template.assert_called_once_with(1)
        self.assertEqual(subject, "Subject: Test RFP")
        self.assertIn("Dr. X", body)
        self.assertIn("$10K", body)
        self.assertIn("March 1", body)

    @patch(
        "research_ai.services.email_generator_service.resolve_expert_search_email_document_context"
    )
    @patch("research_ai.services.email_generator_service.get_email_template")
    def test_fixed_template_uses_user_context(
        self, mock_get_template, mock_resolve_doc
    ):
        rfp_context = {
            "amount": "$10K",
            "deadline": "March 1",
            "title": "Test RFP",
            "url": "https://x.com/g",
            "blurb": "Desc",
        }
        mock_resolve_doc.return_value = ExpertSearchEmailDocumentContext(
            rfp_context_dict=rfp_context,
            proposal_context_dict=None,
            generic_work_context_dict=None,
        )
        expert_search = MagicMock()
        user = SimpleNamespace(
            first_name="Ada",
            last_name="Lovelace",
            email="",
            author_profile=SimpleNamespace(headline="Research Scientist"),
            organization=None,
        )
        et = MagicMock(spec=EmailTemplate)
        et.email_subject = "{{rfp.title}}"
        et.email_body = "Body with {{user.full_name}}."
        mock_get_template.return_value = et
        _, body = generate_expert_email(
            resolved_expert={"honorific": "Dr", "last_name": "X"},
            template=None,
            expert_search=expert_search,
            template_id=1,
            user=user,
        )
        self.assertIn("Body with Ada Lovelace.", body)

    @patch("research_ai.services.email_generator_service.BedrockLLMService")
    def test_llm_path_with_collaboration_key(self, mock_bedrock_class):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "Subject: Hello\n\nBody text here."
        mock_bedrock_class.return_value = mock_llm
        subject, body = generate_expert_email(
            resolved_expert={"honorific": "Dr", "last_name": "Y"},
            template="collaboration",
        )
        self.assertEqual(mock_llm.invoke.call_count, 1)
        self.assertIn("Body text", body or subject or "")

    def test_fixed_path_requires_template_id(self):
        with self.assertRaises(ValueError):
            generate_expert_email(
                resolved_expert={"first_name": "X"},
                template=None,
                template_id=None,
            )
