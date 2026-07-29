"""Model-ref -> provider resolution for the agent core.

Two levers pick a provider:

- The ``RESEARCH_AI_GENERATOR_PROVIDER`` setting (``"claude_platform"``, the
  default, or ``"bedrock"``) selects the generator provider used when no
  explicit model ref is given. It is a real per-environment switch; each
  adapter's model and inference knobs are module constants in the adapter.
- An individual model ref may carry a provider prefix -- ``bedrock:<id>`` routes
  that one model through Bedrock Converse, ``claude_platform:<id>`` through
  Claude Platform on AWS. This is how the judge roster mixes model families
  across providers in one panel.

An unprefixed ref belongs to the configured generator provider, so a Bedrock
deployment's existing ``us.anthropic.*`` ids keep resolving to Bedrock without
being rewritten, and a Claude Platform deployment's bare ``claude-opus-5``
resolves to Claude Platform. The two id namespaces are disjoint (Bedrock
requires an ``anthropic.``-prefixed id or an inference-profile id), so a
mistyped ref surfaces as a 404 from one API rather than silently routing to the
other.

Resolution is intentionally string-only until a provider is actually built:
``generator_model_ref`` never constructs a client, so callers can report the
configured model without paying for (or requiring credentials for) one.
"""

from django.conf import settings

from research_ai.services.agent.providers import bedrock, claude_platform
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider

BEDROCK = "bedrock"
CLAUDE_PLATFORM = "claude_platform"
DEFAULT_PROVIDER = CLAUDE_PLATFORM

_PREFIXES = (f"{BEDROCK}:", f"{CLAUDE_PLATFORM}:")


def generator_provider_name() -> str:
    """The configured generator provider name, validated."""
    name = (settings.RESEARCH_AI_GENERATOR_PROVIDER or DEFAULT_PROVIDER).lower()
    if name not in (BEDROCK, CLAUDE_PLATFORM):
        raise ValueError(
            f"Unknown RESEARCH_AI_GENERATOR_PROVIDER: {name!r} "
            f"(expected {BEDROCK!r} or {CLAUDE_PLATFORM!r})"
        )
    return name


def generator_model_ref() -> str:
    """The configured generator as a model ref (prefixed with its provider)."""
    name = generator_provider_name()
    if name == BEDROCK:
        return f"{BEDROCK}:{bedrock.MODEL_ID}"
    return f"{CLAUDE_PLATFORM}:{claude_platform.MODEL_ID}"


def resolve_provider(
    model_ref: str | None = None,
    *,
    native_tools: frozenset[str] = frozenset(),
) -> LLMProvider:
    """Build the provider for ``model_ref``.

    ``native_tools`` is an explicit per-agent capability request. Unsupported
    names are ignored, so callers can request native search while a Bedrock
    deployment continues to register its local implementation.
    """
    if model_ref is None:
        model_ref = generator_model_ref()
    provider_name, model_id = _split(model_ref)
    if provider_name == BEDROCK:
        return BedrockProvider(model_id=model_id)
    return ClaudePlatformProvider(
        model_id=model_id,
        web_search=claude_platform.WEB_SEARCH_TOOL_NAME in native_tools,
    )


def _split(model_ref: str) -> tuple[str, str | None]:
    """Split ``[<provider>:]<model id>``; an unprefixed ref uses the generator's.

    An empty model id resolves to None so the provider falls back to its own
    settings-backed default.
    """
    for prefix in _PREFIXES:
        if model_ref.startswith(prefix):
            return prefix.removesuffix(":"), model_ref.removeprefix(prefix) or None
    return generator_provider_name(), model_ref or None
