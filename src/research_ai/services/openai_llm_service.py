import logging

from django.conf import settings
from openai import OpenAI

from utils import sentry

logger = logging.getLogger(__name__)


class OpenAIWebSearchLLMService:
    """OpenAI text LLM with web search, drop-in for ``BedrockLLMService``.

    Exposes the same ``invoke(system_prompt, user_prompt)`` signature so it can
    stand in wherever a Bedrock text LLM is injected. The primary path is the
    Responses API with the ``web_search`` tool (so the model can ground its
    answer on the live web); it falls back to plain chat completions if that
    fails.

    Subclasses customize behavior via class attributes (``service_label`` for
    log/error messages, ``default_max_tokens``) and the ``model_id`` argument;
    by default the globally configured ``settings.OPENAI_MODEL`` is used.
    """

    service_label = "OpenAI web search LLM"
    default_max_tokens = 2048

    def __init__(self, *, model_id: str | None = None):
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        self._client = OpenAI(api_key=api_key) if api_key else None
        self.model_id = model_id or settings.OPENAI_MODEL

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Run the prompt with web search, falling back to chat completions.

        Raises:
            RuntimeError: If the API key is missing or both paths fail.
        """
        if not self._client:
            raise RuntimeError(
                f"OPENAI_API_KEY is not configured; cannot run {self.service_label}."
            )

        max_tokens = max_tokens or self.default_max_tokens
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
                sentry.log_error(e2, message=f"{self.service_label} call failed")
                logger.exception("%s failed", self.service_label)
                raise RuntimeError(f"{self.service_label} failed: {e2}") from e2

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
        """Fallback path when web_search fails; ungrounded chat completion."""
        completion = self._client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=max_tokens,
            temperature=temperature,
        )
        choice = completion.choices[0].message
        content = choice.content or ""
        return content.strip()
