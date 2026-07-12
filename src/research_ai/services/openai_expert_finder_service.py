import logging

from django.conf import settings
from openai import OpenAI

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
        max_tokens: int = 16_384,
        temperature: float = 0.0,
    ) -> str:
        """
        Run expert discovery via the Responses API with web search.

        Note that web search must yield results, otherwise the search fails.
        This is deliberate: the expert emails in the output are used for email-based
        outreach, so results must only come from a call where the model can verify
        addresses via web search.

        Returns:
            The model's assistant message as plain text. Callers should treat this as
            a single markdown document whose main payload is a pipe table of experts
            (columns such as name, title, affiliation, expertise, email, notes).

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
            logger.exception("OpenAI expert finder failed")
            raise RuntimeError(f"OpenAI expert finder failed: {e}") from e

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
