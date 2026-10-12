"""Bedrock-powered rewrite of shared EmailTemplate subject/body copy."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from research_ai.models import EmailTemplate
from research_ai.prompts.email_prompts import TEMPLATE_REWRITE_SYSTEM_PROMPT
from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.outreach.template_service import create_template, get_template
from research_ai.services.outreach.template_variables import extract_placeholder_pairs

if TYPE_CHECKING:
    from user.related_models.user_model import User

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```",
    re.IGNORECASE,
)


class TemplateRewriteError(Exception):
    """Base error for template rewrite failures."""


class TemplateNotFoundError(TemplateRewriteError):
    """Raised when the source template does not exist."""


class PlaceholderMismatchError(TemplateRewriteError):
    """Raised when rewritten copy changes the {{entity.field}} set."""


class TemplateRewriteService:
    """Rephrase a template via Bedrock and save a new EmailTemplate."""

    def __init__(self, *, llm: BedrockLLMService | None = None):
        self.llm = llm if llm is not None else BedrockLLMService()

    def rewrite_template(self, user: User, template_id: int) -> EmailTemplate:
        source = get_template(template_id)
        if source is None:
            raise TemplateNotFoundError("Template not found.")

        subject = (source.email_subject or "").strip()
        body = (source.email_body or "").strip()
        source_placeholders = extract_placeholder_pairs(subject, body)

        raw = self.llm.invoke(
            system_prompt=TEMPLATE_REWRITE_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(source.name, subject, body),
            max_tokens=2048,
            temperature=0.4,
        )
        new_subject, new_body = parse_rewrite_response(raw)
        new_placeholders = extract_placeholder_pairs(new_subject, new_body)
        if new_placeholders != source_placeholders:
            raise PlaceholderMismatchError(
                "Rewritten template must keep the same {{entity.field}} "
                "placeholders as the source."
            )

        name = _rewritten_name(source.name)
        return create_template(
            user,
            name=name,
            email_subject=new_subject,
            email_body=new_body,
        )


def parse_rewrite_response(raw: str) -> tuple[str, str]:
    """Parse Bedrock JSON output into (subject, body)."""
    payload = _extract_json_object(raw)
    if not isinstance(payload, dict):
        raise TemplateRewriteError("Rewrite response was not a JSON object.")

    subject = payload.get("email_subject")
    body = payload.get("email_body")
    if not isinstance(subject, str) or not isinstance(body, str):
        raise TemplateRewriteError(
            "Rewrite response must include string email_subject and email_body."
        )
    return subject.strip(), body.strip()


def _build_user_prompt(name: str, subject: str, body: str) -> str:
    return (
        "Rewrite the following outreach email template. Keep every "
        "{{entity.field}} placeholder unchanged.\n\n"
        f"Template name: {name or 'Untitled'}\n\n"
        f"Subject:\n{subject}\n\n"
        f"Body:\n{body}\n\n"
        "Respond with JSON only: "
        '{"email_subject": "...", "email_body": "..."}'
    )


def _rewritten_name(name: str) -> str:
    base = (name or "Template").strip() or "Template"
    suffix = " (rewritten)"
    max_base = 255 - len(suffix)
    if len(base) > max_base:
        base = base[:max_base].rstrip()
    return f"{base}{suffix}"


def _extract_json_object(raw: str) -> object:
    text = (raw or "").strip()
    if not text:
        raise TemplateRewriteError("Rewrite response was empty.")

    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise TemplateRewriteError(
                    "Could not parse rewrite response as JSON."
                ) from exc
        raise TemplateRewriteError("Could not parse rewrite response as JSON.")
