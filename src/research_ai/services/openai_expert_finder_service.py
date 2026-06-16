from research_ai.services.openai_llm_service import OpenAIWebSearchLLMService


class OpenAIExpertFinderService(OpenAIWebSearchLLMService):
    """Call OpenAI for expert-finder table output (markdown).

    Same OpenAI Responses + web_search invocation as the base service; only the
    default token budget and the log/error labels differ. ``invoke`` returns the
    model's assistant message as plain text -- a single markdown document whose
    main payload is a pipe table of experts (columns such as name, title,
    affiliation, expertise, email, notes).
    """

    service_label = "OpenAI expert finder"
    default_max_tokens = 16_384
