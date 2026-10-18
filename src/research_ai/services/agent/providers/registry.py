"""Model-ref -> provider resolution for the agent core.

The ``RESEARCH_AI_GENERATOR_PROVIDER`` setting selects ``claude_platform``
(the default), ``bedrock``, or ``openrouter`` when no explicit model ref is
given. A model ref can instead carry one of those provider prefixes, allowing
the judge roster to mix providers in one panel.

Unprefixed model refs use the configured generator provider. This preserves
existing per-environment rosters while prefixed refs are unambiguous.
Resolution stays string-only until a provider is built, so callers can report
configuration without constructing clients or requiring credentials.

With ``refusal_fallback``, a conversation its model refuses moves to
``RESEARCH_AI_REFUSAL_FALLBACK_MODEL`` (see ``router``).
"""

from django.conf import settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.images import ImageLoader
from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.agent.providers import bedrock, claude_platform, openrouter
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.openrouter import OpenRouterProvider
from research_ai.services.agent.providers.router import RoutedProvider

BEDROCK = "bedrock"
CLAUDE_PLATFORM = "claude_platform"
OPENROUTER = "openrouter"
DEFAULT_PROVIDER = CLAUDE_PLATFORM

_PROVIDERS = (BEDROCK, CLAUDE_PLATFORM, OPENROUTER)
_ADAPTERS = {
    BEDROCK: bedrock,
    CLAUDE_PLATFORM: claude_platform,
    OPENROUTER: openrouter,
}
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
    return f"{name}:{_ADAPTERS[name].MODEL_ID}"


def default_effort(model_ref: str) -> str | None:
    """Resolve the adapter's supported effort default without building a client."""
    provider_name, model_id = split_model_ref(model_ref)
    if provider_name == BEDROCK:
        return None
    adapter = openrouter if provider_name == OPENROUTER else claude_platform
    capabilities = model_capabilities(provider_name, model_id or adapter.MODEL_ID)
    return adapter.EFFORT if adapter.EFFORT in capabilities.effort else None


def resolve_provider(
    model_ref: str | None = None,
    *,
    native_tools: frozenset[str] = frozenset(),
    effort: str | None = None,
    thinking: str | None = None,
    image_loader: ImageLoader | None = None,
    refusal_fallback: bool = False,
) -> LLMProvider:
    """Build the provider for ``model_ref``.

    ``native_tools`` is an explicit per-agent capability request. Unsupported
    names are ignored, so callers can request native search while Bedrock and
    OpenRouter continue to use their local implementations. ``image_loader``
    supplies the bytes of images in the conversation. ``refusal_fallback``
    wraps the provider in a ``RoutedProvider``; a model it moves the
    conversation to runs on its adapter's effort and thinking defaults.
    """
    if model_ref is None:
        model_ref = generator_model_ref()
    provider = _build_provider(
        model_ref,
        native_tools=native_tools,
        effort=effort,
        thinking=thinking,
        image_loader=image_loader,
    )
    if not refusal_fallback:
        return provider
    fallback = settings.RESEARCH_AI_REFUSAL_FALLBACK_MODEL
    return RoutedProvider(
        primary_ref=_canonical_model_ref(model_ref),
        primary=provider,
        fallback_ref=_canonical_model_ref(fallback) if fallback else None,
        build=lambda ref: _build_routed_provider(
            ref, native_tools=native_tools, image_loader=image_loader
        ),
    )


def _build_routed_provider(
    model_ref: str, *, native_tools: frozenset[str], image_loader: ImageLoader | None
) -> LLMProvider:
    """A model the router moves a conversation to, refused unless it is priced."""
    # Imported here because model_pricing imports this module.
    from research_ai.services.agent.model_pricing import model_pricing

    provider_name, model_id = split_model_ref(model_ref)
    # The budget guard prices only the conversation's own model, so the model
    # actually called is checked here before anything is spent on it.
    if model_pricing(provider_name, model_id or "") is None:
        raise ProviderError(
            f"routed model {model_ref} has no reviewed pricing", retryable=False
        )
    return _build_provider(
        model_ref, native_tools=native_tools, image_loader=image_loader
    )


def _build_provider(
    model_ref: str,
    *,
    native_tools: frozenset[str],
    image_loader: ImageLoader | None,
    effort: str | None = None,
    thinking: str | None = None,
) -> LLMProvider:
    provider_name, model_id = split_model_ref(model_ref)
    if provider_name == BEDROCK:
        return BedrockProvider(model_id=model_id, image_loader=image_loader)
    if provider_name == OPENROUTER:
        return OpenRouterProvider(
            model_id=model_id,
            effort=effort,
            thinking=thinking,
            image_loader=image_loader,
        )
    return ClaudePlatformProvider(
        model_id=model_id,
        web_search=claude_platform.WEB_SEARCH_TOOL_NAME in native_tools,
        effort=effort,
        thinking=thinking,
        image_loader=image_loader,
    )


def _canonical_model_ref(model_ref: str) -> str:
    """``model_ref`` with its provider prefix and default model id filled in."""
    provider_name, model_id = split_model_ref(model_ref)
    return f"{provider_name}:{model_id or _ADAPTERS[provider_name].MODEL_ID}"


def split_model_ref(model_ref: str) -> tuple[str, str | None]:
    """Split ``[<provider>:]<model id>``; bare refs use the generator provider."""
    for prefix in _PREFIXES:
        if model_ref.startswith(prefix):
            return prefix.removesuffix(":"), model_ref.removeprefix(prefix) or None
    return generator_provider_name(), model_ref or None
