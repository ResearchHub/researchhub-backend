"""AI-written social posts for sharing proposals and RFPs.

The share modal offers a ready-to-edit post for X, LinkedIn and Bluesky
instead of the bare title. The post depends only on the document, not on who
shares it, so one generation per document version is cached and served to
every sharer.
"""

import hashlib
import logging
import re

from django.conf import settings
from django.core.cache import cache as default_cache
from openai import OpenAI

from research_ai.prompts.social_share_prompts import (
    build_share_post_system_prompt,
    build_share_post_user_prompt,
)
from research_ai.services.agent import (
    AssistantTurn,
    LLMProvider,
    Message,
    OpenRouterProvider,
    ProviderError,
    StopReason,
    TextBlock,
)
from research_ai.services.agent.providers.openrouter import OPENROUTER_BASE_URL
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import (
    ResearchhubPost,
)

logger = logging.getLogger(__name__)

MODEL_ID = "moonshotai/kimi-k3"

SHAREABLE_DOCUMENT_TYPES = (PREREGISTRATION, GRANT)

_DOCUMENT_KINDS = {
    PREREGISTRATION: "Research proposal",
    GRANT: "Request for proposals (RFP)",
}

# X is the tightest of the three platforms: it counts every link as 23
# characters and the share intent joins the link to the text with a space,
# leaving 256 for the text. The model is asked for less
# so a slight overshoot still fits.
MAX_POST_CHARS = 280 - 23 - 1
TARGET_POST_CHARS = 220
GENERATION_ATTEMPTS = 2

# Enough of the description to say what the work is about, without paying for
# the whole document on every new version.
MAX_BODY_CHARS = 6000

# The modal waits on this request, so a slow model fails fast to the title.
REQUEST_TIMEOUT_SECONDS = 25

CACHE_TTL_SECONDS = 60 * 60 * 24 * 7

_URL_PATTERN = re.compile(r"https?://\S+")
_WRAPPING_QUOTES = "\"'“”‘’"


class SharePostGenerationError(Exception):
    """The model could not produce a usable post."""


def _default_provider() -> LLMProvider:
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=settings.OPENROUTER_API_KEY or "",
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=1,
    )
    # Reasoning off: a short post gains little from it and the user is waiting.
    return OpenRouterProvider(client=client, model_id=MODEL_ID, thinking="disabled")


class SocialShareService:
    def __init__(self, provider: LLMProvider | None = None, cache=default_cache):
        self._provider = provider
        self._cache = cache

    def share_post_text(self, post: ResearchhubPost) -> str:
        """The share post for ``post``, generated once per version of its content."""
        user_prompt = self._user_prompt(post)
        # Keyed on the prompt itself: grants and fundraises are saved apart
        # from the post, so its own timestamp misses their edits.
        digest = hashlib.sha256(
            f"{build_share_post_system_prompt(TARGET_POST_CHARS)}\0{user_prompt}".encode()
        ).hexdigest()
        key = f"research_ai:share_post:v2:{post.id}:{digest}"
        cached = self._cache.get(key)
        if cached:
            return cached

        text = self._generate(user_prompt)
        self._cache.set(key, text, CACHE_TTL_SECONDS)
        return text

    def _generate(self, user_prompt: str) -> str:
        if self._provider is None:
            if not settings.OPENROUTER_API_KEY:
                raise SharePostGenerationError("OPENROUTER_API_KEY is not configured")
            self._provider = _default_provider()

        messages = [Message(role="user", content=[TextBlock(text=user_prompt)])]
        text = ""
        # Models miscount characters, so an overlong draft gets one rewrite
        # before it is cut, which reads worse than a post written to fit.
        for _ in range(GENERATION_ATTEMPTS):
            turn = self._complete(messages)
            text = normalize_post_text(turn.text)
            if not text:
                raise SharePostGenerationError("model returned no post text")
            if len(text) <= MAX_POST_CHARS:
                return text
            messages = [
                *messages,
                Message(role="assistant", content=[TextBlock(text=turn.text)]),
                Message(
                    role="user",
                    content=[
                        TextBlock(
                            text=(
                                f"That is {len(text)} characters. Rewrite it in "
                                f"under {TARGET_POST_CHARS} characters."
                            )
                        )
                    ],
                ),
            ]
        return fit_post_text(text)

    def _complete(self, messages: list[Message]) -> AssistantTurn:
        try:
            turn = self._provider.complete(
                system_prompt=build_share_post_system_prompt(TARGET_POST_CHARS),
                messages=messages,
                rendered_tools=[],
                max_tokens=400,
                temperature=0.7,
            )
        except ProviderError as e:
            raise SharePostGenerationError(str(e)) from e
        if turn.stop_reason == StopReason.CONTENT_FILTERED:
            raise SharePostGenerationError("model refused the post")
        return turn

    def _user_prompt(self, post: ResearchhubPost) -> str:
        body = post.renderable_text or ""
        if post.document_type == GRANT:
            grant = post.unified_document.grants.first()
            details = _grant_details(grant)
            if grant is not None:
                body = body or grant.description or ""
        else:
            details = _fundraise_details(post.unified_document.fundraises.first())

        return build_share_post_user_prompt(
            document_kind=_DOCUMENT_KINDS[post.document_type],
            title=post.title,
            body=body[:MAX_BODY_CHARS],
            details=details,
        )


def _grant_details(grant) -> list[str]:
    if grant is None:
        return []
    details = []
    if grant.amount:
        details.append(f"Funding: {_format_amount(grant.amount, grant.currency)}")
    if grant.organization:
        details.append(f"Funder: {grant.organization}")
    if grant.end_date:
        details.append(f"Application deadline: {grant.end_date:%B %-d, %Y}")
    return details


def _fundraise_details(fundraise) -> list[str]:
    if fundraise is None or not fundraise.goal_amount:
        return []
    goal = _format_amount(fundraise.goal_amount, fundraise.goal_currency)
    return [f"Funding goal: {goal}"]


def _format_amount(amount, currency: str) -> str:
    return f"{amount:,.0f} {currency}"


def normalize_post_text(raw: str) -> str:
    """Strip what the model should not have written around the post itself."""
    text = raw.strip()
    if len(text) >= 2 and text[0] in _WRAPPING_QUOTES and text[-1] in _WRAPPING_QUOTES:
        text = text[1:-1].strip()
    # The link is attached by the share intent; a second one would be noise.
    text = _URL_PATTERN.sub("", text)
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fit_post_text(text: str) -> str:
    """Cut ``text`` to fit beside the link: at a sentence end, else a word."""
    if len(text) <= MAX_POST_CHARS:
        return text
    head = text[:MAX_POST_CHARS]
    sentence_end = max(head.rfind(mark) for mark in (". ", "! ", "? ", ".\n"))
    if sentence_end >= MAX_POST_CHARS // 2:
        return head[: sentence_end + 1]
    cut = head[: MAX_POST_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:-") + "…"
