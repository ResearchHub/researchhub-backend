import logging

from django.conf import settings
from openai import OpenAI

from ai_peer_review.prompts.proposal_review_prompts import (
    get_openai_web_context_system_prompt,
)
from utils import sentry

logger = logging.getLogger(__name__)

PROPOSAL_REVIEW_WEB_MODEL = "gpt-5.4-mini"


def fetch_proposal_review_web_context(
    proposal_excerpt: str,
    author_hint: str,
    *,
    max_output_tokens: int = 2048,
    max_input_proposal_chars: int = 8000,
    max_input_author_chars: int = 2000,
    max_return_chars: int = 6000,
) -> str:
    """
    Return a bounded bullet list for the Bedrock user prompt.
    """
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        logger.warning(
            "OPENAI_API_KEY is empty; skipping proposal review web search context"
        )
        return ""

    system_prompt = get_openai_web_context_system_prompt()
    client = OpenAI(api_key=api_key)
    user = (
        "Proposal excerpt (truncated):\n"
        f"{(proposal_excerpt or '')[:max_input_proposal_chars]}\n\n"
        "Author / affiliation hint (from platform profile):\n"
        f"{(author_hint or '')[:max_input_author_chars]}\n"
    )

    try:
        response = client.responses.create(
            model=PROPOSAL_REVIEW_WEB_MODEL,
            instructions=system_prompt,
            input=user,
            tools=[{"type": "web_search"}],
            max_output_tokens=max_output_tokens,
            temperature=0.0,
        )
        text = (response.output_text or "").strip()
    except Exception as e:
        logger.warning(
            "OpenAI web context for proposal review failed: %s", e, exc_info=True
        )
        sentry.log_error(e, message="OpenAI proposal review web context failed")
        try:
            completion = client.chat.completions.create(
                model=PROPOSAL_REVIEW_WEB_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_output_tokens,
                temperature=0.0,
            )
            text = (completion.choices[0].message.content or "").strip()
        except Exception as e2:
            sentry.log_error(
                e2,
                message="OpenAI proposal review web context fallback failed",
            )
            logger.exception("OpenAI proposal review web context fallback failed")
            return ""

    if len(text) > max_return_chars:
        return text[:max_return_chars] + "\n[TRUNCATED]"
    return text
