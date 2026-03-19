from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import EmailTemplate
from research_ai.services.email_generator_service import (
    _build_signature_block,
    _normalize_template_data,
    _parse_subject_and_body,
    _replace_placeholders,
    _strip_existing_signature,
    _strip_markdown,
    generate_expert_email,
)


class NormalizeTemplateDataTests(TestCase):
    def test_empty_or_none_returns_empty_dict(self):
        self.assertEqual(_normalize_template_data(None), {})
        self.assertEqual(_normalize_template_data({}), {})

    def test_maps_contact_keys_to_normalized_keys(self):
        data = {
            "contact_name": " Jane ",
            "contact_title": " Prof ",
            "contact_institution": " MIT ",
            "contact_email": " jane@mit.edu ",
            "contact_phone": " 555-1234 ",
            "contact_website": " https://example.com ",
        }
        out = _normalize_template_data(data)
        self.assertEqual(out["name"], "Jane")
        self.assertEqual(out["title"], "Prof")
        self.assertEqual(out["institution"], "MIT")
        self.assertEqual(out["email"], "jane@mit.edu")
        self.assertEqual(out["phone"], "555-1234")
        self.assertEqual(out["website"], "https://example.com")

    def test_missing_keys_become_empty_string(self):
        out = _normalize_template_data({"contact_name": "Only"})
        self.assertEqual(out["name"], "Only")
        self.assertEqual(out["title"], "")
        self.assertEqual(out["institution"], "")
        self.assertEqual(out["email"], "")
        self.assertEqual(out["phone"], "")
        self.assertEqual(out["website"], "")


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
            resolved_expert={"name": "Dr. Smith", "title": "Professor"},
            template_data=None,
        )

        self.assertEqual(subject, "Invitation to collaborate")
        self.assertIn("Dear Dr. Smith", body)
        mock_llm.invoke.assert_called_once()

    @patch("research_ai.services.email_generator_service.BedrockLLMService")
    @patch("research_ai.services.email_generator_service.build_email_prompt")
    def test_post_processes_with_template_data_and_signature(
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

        subject, body = generate_expert_email(
            resolved_expert={"name": "Expert"},
            template_data={
                "contact_name": "Jane Doe",
                "contact_institution": "MIT",
            },
        )

        self.assertIn("Jane Doe", body)
        self.assertIn("MIT", body)
        self.assertTrue(body.strip().endswith("MIT"))
        self.assertNotIn("[Your Name]", body)
        self.assertNotIn("[Institution]", body)

    @patch("research_ai.services.email_generator_service.get_email_template")
    @patch("research_ai.services.email_generator_service.build_rfp_context")
    @patch("research_ai.services.email_generator_service.resolve_grant")
    def test_generate_expert_email_fixed_template_with_rfp_uses_variable_substitution(
        self, mock_resolve_grant, mock_build_rfp_context, mock_get_template
    ):
        rfp_context = {
            "amount": "$10K",
            "deadline": "March 1",
            "title": "Test RFP",
            "url": "https://x.com/g",
            "blurb": "RFP description",
        }
        mock_build_rfp_context.return_value = rfp_context
        mock_resolve_grant.return_value = MagicMock()
        expert_search = MagicMock()
        user = MagicMock()
        et = MagicMock(spec=EmailTemplate)
        et.template_type = EmailTemplate.TemplateType.FIXED
        et.email_subject = "Subject: {{rfp.title}}"
        et.email_body = "Hi {{expert.name}}, see {{rfp.amount}} and {{rfp.deadline}}."
        mock_get_template.return_value = et
        subject, body = generate_expert_email(
            resolved_expert={"name": "Dr. X"},
            template="rfp-outreach",
            expert_search=expert_search,
            template_id=1,
            user=user,
        )
        mock_get_template.assert_called_once_with(1)
        self.assertEqual(subject, "Subject: Test RFP")
        self.assertIn("Dr. X", body)
        self.assertIn("$10K", body)
        self.assertIn("March 1", body)

    @patch("research_ai.services.email_generator_service.get_email_template")
    @patch("research_ai.services.email_generator_service.build_rfp_context")
    @patch("research_ai.services.email_generator_service.resolve_grant")
    def test_generate_expert_email_fixed_template_uses_user_context_for_signature(
        self, mock_resolve_grant, mock_build_rfp_context, mock_get_template
    ):
        rfp_context = {
            "amount": "$10K",
            "deadline": "March 1",
            "title": "Test RFP",
            "url": "https://x.com/g",
            "blurb": "Desc",
        }
        mock_build_rfp_context.return_value = rfp_context
        mock_resolve_grant.return_value = MagicMock()
        expert_search = MagicMock()
        expert_search.created_by.first_name = "Ada"
        expert_search.created_by.last_name = "Lovelace"
        expert_search.created_by.author_profile.headline = "Research Scientist"
        user = MagicMock()
        et = MagicMock(spec=EmailTemplate)
        et.template_type = EmailTemplate.TemplateType.FIXED
        et.email_subject = "{{rfp.title}}"
        et.email_body = "Body with {{user.full_name}}."
        mock_get_template.return_value = et
        _, body = generate_expert_email(
            resolved_expert={"name": "Dr. X"},
            template="rfp-outreach",
            expert_search=expert_search,
            template_id=1,
            user=user,
            template_data={
                "contact_name": "Ada Lovelace",
                "contact_title": "Research Scientist",
                "contact_institution": "",
                "contact_email": "",
                "contact_phone": "",
                "contact_website": "",
            },
        )
        self.assertIn("Body with Ada Lovelace.", body)
        self.assertTrue(
            body.strip().endswith("Research Scientist") or "Ada Lovelace" in body
        )

    @patch("research_ai.services.email_generator_service.BedrockLLMService")
    def test_generate_expert_email_without_template_uses_llm(self, mock_bedrock_class):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "Subject: Hello\n\nBody text here."
        mock_bedrock_class.return_value = mock_llm
        subject, body = generate_expert_email(
            resolved_expert={"name": "Dr. Y"},
            template="collaboration",
        )
        self.assertEqual(mock_llm.invoke.call_count, 1)
        self.assertIn("Body text", body or subject or "")
