"""
Generate expert outreach emails via Bedrock.
Ported from expertfinder generate-expert-email route; uses Bedrock instead of Vercel AI.
"""

import logging
import re

from research_ai.prompts.email_prompts import build_email_prompt
from research_ai.services.bedrock_llm_service import BedrockLLMService

logger = logging.getLogger(__name__)

# System instruction for email generation (no extra rules; all in user prompt)
EMAIL_SYSTEM_PROMPT = (
    "You are a professional email writer. Generate concise, authentic "
    "outreach emails. Follow the format and rules in the user message exactly."
)


def _parse_subject_and_body(text: str) -> tuple[str, str]:
    """
    Parse LLM output that should be in the form:
    Subject: [subject line]

    [Email body...]
    """
    subject = ""
    body = text.strip()
    subject_match = re.match(r"(?i)^Subject:\s*(.+?)(?:\n\n|\n\s*\n)", body, re.DOTALL)
    if subject_match:
        subject = subject_match.group(1).strip()
        body = body[subject_match.end():].strip()
    else:
        # Try single line Subject: ...
        subject_match = re.match(r"(?i)^Subject:\s*(.+)$", body, re.MULTILINE)
        if subject_match:
            subject = subject_match.group(1).strip()
            body = re.sub(r"(?i)^Subject:\s*.+$", "", body, count=1).strip()
    return subject, body


def generate_expert_email(
    expert_name: str,
    expert_title: str = "",
    expert_affiliation: str = "",
    expertise: str = "",
    notes: str = "",
    template: str = "collaboration",
    custom_use_case: str | None = None,
) -> tuple[str, str]:
    """
    Generate subject and body for an expert outreach email using Bedrock.

    template: one of collaboration, consultation, conference, peer-review,
              publication, rfp-outreach, custom. For custom, pass custom_use_case.

    Returns:
        (email_subject, email_body)
    """
    prompt = build_email_prompt(
        expert_name=expert_name or "",
        expert_title=expert_title or "",
        expert_affiliation=expert_affiliation or "",
        expertise=expertise or "",
        notes=notes or "",
        template=template,
        custom_use_case=custom_use_case,
    )
    service = BedrockLLMService()
    raw = service.invoke(
        system_prompt=EMAIL_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=1024,
        temperature=0.3,
    )
    subject, body = _parse_subject_and_body(raw)
    return subject, body
