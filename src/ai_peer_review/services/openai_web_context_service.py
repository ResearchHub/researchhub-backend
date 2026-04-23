import logging

from django.conf import settings
from openai import OpenAI

from ai_peer_review.prompts.proposal_review_prompts import (
    get_openai_web_context_system_prompt,
)
from utils import sentry

logger = logging.getLogger(__name__)

OPENAI_WEB_CONTEXT_MODEL = getattr(
    settings,
    "AI_PEER_REVIEW_OPENAI_WEB_CONTEXT_MODEL",
    "gpt-5.4-mini",
)


class OpenAIReviewContextService:
    """Produce bullet web-search notes to inject into proposal review prompts."""

    def __init__(self):
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        self._client = OpenAI(api_key=api_key) if api_key else None
        self.model_id = OPENAI_WEB_CONTEXT_MODEL

    def build_user_prompt(
        self,
        *,
        proposal_excerpt: str,
        researcher_display_name: str | None = None,
        institutional_affiliation: str | None = None,
    ) -> str:
        text = (proposal_excerpt or "").strip()
        if len(text) > 24000:
            text = text[:24000] + "\n\n[TRUNCATED]"
        parts = [
            "Use web search to ground your bullets in public sources.",
            "",
            "PROPOSAL EXCERPT:",
            text,
        ]
        if researcher_display_name and researcher_display_name.strip():
            parts.extend(
                [
                    "",
                    "NAMED RESEARCHER (if relevant):",
                    researcher_display_name.strip(),
                ]
            )
        if institutional_affiliation and institutional_affiliation.strip():
            parts.extend(["", "AFFILIATION HINT:", institutional_affiliation.strip()])
        return "\n".join(parts)

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        if not self._client:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured; cannot run web context pass."
            )
        try:
            return self._invoke_with_web_search(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            logger.warning(
                "OpenAI Responses API with web_search failed, falling back to chat: %s",
                e,
            )
            try:
                return self._invoke_chat_completions(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as e2:
                sentry.log_error(e2, message="OpenAI web context API call failed")
                logger.exception("OpenAI web context failed")
                raise RuntimeError(f"OpenAI web context failed: {e2}") from e2

    def _invoke_with_web_search(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = self._client.responses.create(
            model=self.model_id,
            instructions=system_prompt,
            input=user_prompt,
            tools=[{"type": "web_search"}],
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        return (response.output_text or "").strip()

    def _invoke_chat_completions(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        completion = self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = completion.choices[0].message
        content = choice.content or ""
        return content.strip()

    def fetch_proposal_web_context(
        self,
        *,
        proposal_text: str,
        researcher_display_name: str | None = None,
        institutional_affiliation: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        system = get_openai_web_context_system_prompt()
        user = self.build_user_prompt(
            proposal_excerpt=proposal_text,
            researcher_display_name=researcher_display_name,
            institutional_affiliation=institutional_affiliation,
        )
        return self.invoke(
            system,
            user,
            max_tokens=max_tokens,
            temperature=temperature,
        )


def fetch_proposal_review_web_context(
    proposal_excerpt: str,
    author_hint: str,
    *,
    max_output_tokens: int = 2048,
    max_input_proposal_chars: int = 8000,
    max_input_author_chars: int = 2000,
    max_return_chars: int = 6000,
) -> str:
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        logger.warning(
            "OPENAI_API_KEY is empty; skipping proposal review web search context"
        )
        return ""
    svc = OpenAIReviewContextService()
    if not svc._client:
        return ""
    try:
        text = svc.fetch_proposal_web_context(
            proposal_text=(proposal_excerpt or "")[:max_input_proposal_chars],
            researcher_display_name=(author_hint or "")[:max_input_author_chars]
            or None,
            institutional_affiliation=None,
            max_tokens=max_output_tokens,
            temperature=0.0,
        )
    except Exception as e:
        logger.warning(
            "OpenAI web context for proposal review failed: %s", e, exc_info=True
        )
        sentry.log_error(e, message="OpenAI proposal review web context failed")
        return ""
    if len(text) > max_return_chars:
        return text[:max_return_chars] + "\n[TRUNCATED]"
    return text
