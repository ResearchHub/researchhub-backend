import logging

from django.conf import settings
from openai import OpenAI

from utils import sentry

logger = logging.getLogger(__name__)

OPENAI_EXPERT_FINDER_MODEL = "gpt-5.4-mini"


class OpenAIExpertFinderService:
    """Call OpenAI for expert-finder table output (markdown)."""

    def __init__(self):
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        self._client = OpenAI(api_key=api_key) if api_key else None
        self.model_id = OPENAI_EXPERT_FINDER_MODEL

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> str:
        """
        Run expert discovery. Returns assistant text (expected: markdown expert table).

        Raises:
            RuntimeError: If API key is missing or the API call fails.
        """
        if not self._client:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured; cannot run expert discovery."
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
                "OpenAI Responses API with web_search failed, falling back to chat "
                "completions: %s",
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
                sentry.log_error(e2, message="OpenAI expert finder API call failed")
                logger.exception("OpenAI expert finder failed")
                raise RuntimeError(f"OpenAI expert finder failed: {e2}") from e2

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
        text = (response.output_text or "").strip()
        if not text:
            logger.warning("OpenAI Responses returned empty output_text")
        return text

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
