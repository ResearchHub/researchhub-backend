"""AI-written social posts for sharing proposals and RFPs.

The share modal offers a ready-to-edit post for X, LinkedIn and Bluesky
instead of the bare title. The post depends only on the document, not on who
shares it, so one generation per document version is cached and served to
every sharer.

The API never calls the model: on a cache miss it queues a Celery task, and the
worker generates and caches the post while the modal polls for it.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache as default_cache
from openai import OpenAI

from purchase.related_models.fundraise_model import Fundraise
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

# The modal waits on the post, so a slow model fails fast to the title.
REQUEST_TIMEOUT_SECONDS = 25

CACHE_TTL_SECONDS = 60 * 60 * 24 * 7

# The slowest generation: two attempts, each a request and one retry.
GENERATION_TIME_LIMIT_SECONDS = GENERATION_ATTEMPTS * 2 * REQUEST_TIMEOUT_SECONDS + 10
# One task generates each post; the lock stops other requests from queueing
# more. It outlives the task, with slack for time spent waiting in the queue.
GENERATION_LOCK_SECONDS = GENERATION_TIME_LIMIT_SECONDS + 60
# A failed generation is reported to pollers, then retried by a later share.
FAILURE_TTL_SECONDS = 60

_URL_PATTERN = re.compile(r"https?://\S+")
_WRAPPING_QUOTES = "\"'“”‘’"


class SharePostGenerationError(Exception):
    """The model could not produce a usable post."""


@dataclass(frozen=True)
class SharePost:
    """Where a post's generation stands: ``ready`` (with text), ``pending``
    or ``failed``."""

    status: str
    text: str | None = None


READY = "ready"
PENDING = "pending"
FAILED = "failed"


def _enqueue_generation(post_id: int, lock_key: str, token: str) -> None:
    # Imported here: the tasks module imports this one.
    from research_ai.tasks import generate_share_post_task

    generate_share_post_task.delay(post_id, lock_key, token)


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
    def __init__(
        self,
        provider: LLMProvider | None = None,
        cache=default_cache,
        enqueue: Callable[[int, str, str], None] = _enqueue_generation,
    ):
        self._provider = provider
        self._cache = cache
        self._enqueue = enqueue

    def request_post(
        self, post: ResearchhubPost, on_enqueue: Callable[[], None] | None = None
    ) -> SharePost:
        """The share post for ``post``, queueing its generation on a miss.

        ``on_enqueue`` runs just before a task is queued, so a caller can rate
        limit generations without limiting the polls that follow one.
        """
        key = self._cache_key(post, self._user_prompt(post))
        cached = self._cache.get(key)
        if cached:
            return SharePost(READY, cached)
        if self._cache.get(_failure_key(key)):
            return SharePost(FAILED)

        lock_key = _lock_key(key)
        token = uuid.uuid4().hex
        if not self._cache.add(lock_key, token, GENERATION_LOCK_SECONDS):
            return SharePost(PENDING)
        try:
            if on_enqueue is not None:
                on_enqueue()
            self._enqueue(post.id, lock_key, token)
        except BaseException:
            self._release(lock_key, token)
            raise
        return SharePost(PENDING)

    def generate_and_cache(self, post_id: int, lock_key: str, token: str) -> None:
        """Generate the post for ``post_id`` and cache it (worker side)."""
        try:
            post = ResearchhubPost.objects.filter(pk=post_id).first()
            if post is None:
                return
            user_prompt = self._user_prompt(post)
            key = self._cache_key(post, user_prompt)
            try:
                text = self._generate(user_prompt)
            except SharePostGenerationError:
                logger.warning(
                    "Share post generation failed for post %s", post_id, exc_info=True
                )
                self._cache.set(_failure_key(key), True, FAILURE_TTL_SECONDS)
                return
            self._cache.set(key, text, CACHE_TTL_SECONDS)
        finally:
            self._release(lock_key, token)

    def _cache_key(self, post: ResearchhubPost, user_prompt: str) -> str:
        # Keyed on the prompt itself: grants and fundraises are saved apart
        # from the post, so its own timestamp misses their edits.
        digest = hashlib.sha256(
            f"{build_share_post_system_prompt(TARGET_POST_CHARS)}\0{user_prompt}".encode()
        ).hexdigest()
        return f"research_ai:share_post:v2:{post.id}:{digest}"

    def _release(self, lock_key: str, token: str) -> None:
        # A task that outlived the lock must not free a newer request's lock.
        # Django's cache has no compare-and-delete, so a race remains between
        # these two calls; it costs one extra generation.
        if self._cache.get(lock_key) == token:
            self._cache.delete(lock_key)

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
            length = x_weighted_length(text)
            if length <= MAX_POST_CHARS:
                return text
            messages = [
                *messages,
                Message(role="assistant", content=[TextBlock(text=turn.text)]),
                Message(
                    role="user",
                    content=[
                        TextBlock(
                            text=(
                                f"That is {length} characters. Rewrite it in "
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
            if grant is not None and grant.description:
                # The grant's own description is edited apart from the post
                # body and often holds the purpose and applicant requirements.
                body = f"{grant.description}\n\n{body}".strip()
        else:
            details = _fundraise_details(post.unified_document.fundraises.first())

        return build_share_post_user_prompt(
            document_kind=_DOCUMENT_KINDS[post.document_type],
            title=post.title,
            body=body[:MAX_BODY_CHARS],
            details=details,
        )


def _lock_key(key: str) -> str:
    return f"lock:{key}"


def _failure_key(key: str) -> str:
    return f"failed:{key}"


def _grant_details(grant) -> list[str]:
    # An RFP can be posted without a grant; it takes no applications.
    if grant is None:
        return ["Status: Closed to applications"]
    status = "Open for applications" if grant.is_active() else "Closed to applications"
    details = [f"Status: {status}"]
    if grant.amount:
        details.append(f"Funding: {_format_amount(grant.amount, grant.currency)}")
    if grant.organization:
        details.append(f"Funder: {grant.organization}")
    if grant.end_date:
        details.append(f"Application deadline: {grant.end_date:%B %-d, %Y}")
    return details


def _fundraise_details(fundraise) -> list[str]:
    # A proposal can be published without a fundraise; it takes no funding.
    is_open = (
        fundraise is not None
        and fundraise.status == Fundraise.OPEN
        and not fundraise.is_expired()
    )
    details = [f"Funding status: {'Open' if is_open else 'Closed'}"]
    if fundraise is not None and fundraise.goal_amount:
        goal = _format_amount(fundraise.goal_amount, fundraise.goal_currency)
        details.append(f"Funding goal: {goal}")
    return details


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
    if x_weighted_length(text) <= MAX_POST_CHARS:
        return text
    head = _x_prefix(text, MAX_POST_CHARS)
    sentence_end = max(head.rfind(mark) for mark in (". ", "! ", "? ", ".\n"))
    if sentence_end >= len(head) // 2:
        return head[: sentence_end + 1]
    # Leave room for the ellipsis, which X counts twice.
    cut = _x_prefix(text, MAX_POST_CHARS - x_weighted_length("…"))
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:-") + "…"


# X's twitter-text weights: code points in these ranges count once, everything
# else (CJK, emoji, most symbols) twice. Weighing each code point of an emoji
# sequence on its own overcounts joined emoji, which only errs on the short side.
_X_SINGLE_WEIGHT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)


def _x_char_weight(char: str) -> int:
    code_point = ord(char)
    if any(low <= code_point <= high for low, high in _X_SINGLE_WEIGHT_RANGES):
        return 1
    return 2


def x_weighted_length(text: str) -> int:
    """Length of ``text`` as X counts it toward the 280-character limit."""
    return sum(_x_char_weight(char) for char in text)


def _x_prefix(text: str, budget: int) -> str:
    """The longest start of ``text`` whose X-weighted length fits ``budget``."""
    total = 0
    for index, char in enumerate(text):
        total += _x_char_weight(char)
        if total > budget:
            return text[:index]
    return text
