"""Model-ref -> provider resolution for the agent core.

The ``RESEARCH_AI_GENERATOR_PROVIDER`` setting selects ``openrouter``
(the default), ``claude_platform``, or ``bedrock`` when no explicit model ref is
given. A model ref can instead carry one of those provider prefixes, allowing
the judge roster to mix providers in one panel.

Unprefixed model refs use the configured generator provider. This preserves
existing per-environment rosters while prefixed refs are unambiguous.
Resolution stays string-only until a provider is built, so callers can report
configuration without constructing clients or requiring credentials.
"""

from django.conf import settings

from research_ai.services.agent.providers import bedrock, claude_platform, openrouter
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.openrouter import OpenRouterProvider

BEDROCK = "bedrock"
CLAUDE_PLATFORM = "claude_platform"
OPENROUTER = "openrouter"
DEFAULT_PROVIDER = OPENROUTER

_PROVIDERS = (BEDROCK, CLAUDE_PLATFORM, OPENROUTER)
_PREFIXES = tuple(f"{provider}:" for provider in _PROVIDERS)


def generator_provider_name() -> str:
    """Return the configured generator provider name after validation."""
    name = (settings.RESEARCH_AI_GENERATOR_PROVIDER or DEFAULT_PROVIDER).lower()
    if name not in _PROVIDERS:
        expected = ", ".join(repr(provider) for provider in _PROVIDERS)
        raise ValueError(
            f"Unknown RESEARCH_AI_GENERATOR_PROVIDER: {name!r} "
            f"(expected one of {expected})"
        )
    return name


def generator_model_ref() -> str:
    """Return the configured generator as a provider-prefixed model ref."""
    name = generator_provider_name()
    model_ids = {
        BEDROCK: bedrock.MODEL_ID,
        CLAUDE_PLATFORM: claude_platform.MODEL_ID,
        OPENROUTER: openrouter.MODEL_ID,
    }
    return f"{name}:{model_ids[name]}"


def resolve_provider(
    model_ref: str | None = None,
    *,
    native_tools: frozenset[str] = frozenset(),
) -> LLMProvider:
    """Build the provider for ``model_ref``.

    ``native_tools`` is an explicit per-agent capability request. Unsupported
    names are ignored, so callers can request native search while Bedrock and
    OpenRouter continue to use their local implementations.
    """
    if model_ref is None:
        model_ref = generator_model_ref()
    provider_name, model_id = _split(model_ref)
    if provider_name == BEDROCK:
        return BedrockProvider(model_id=model_id)
    if provider_name == OPENROUTER:
        return OpenRouterProvider(model_id=model_id)
    return ClaudePlatformProvider(
        model_id=model_id,
        web_search=claude_platform.WEB_SEARCH_TOOL_NAME in native_tools,
    )


def _split(model_ref: str) -> tuple[str, str | None]:
    """Split ``[<provider>:]<model id>``; bare refs use the generator provider."""
    for prefix in _PREFIXES:
        if model_ref.startswith(prefix):
            return prefix.removesuffix(":"), model_ref.removeprefix(prefix) or None
    return generator_provider_name(), model_ref or None
