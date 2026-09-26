"""Expert finder: the search pipeline that turns an RFP/query into experts.

- ``finder`` -- the ``ExpertFinderService`` pipeline and the
  ``run_expert_finder_search`` entry point.
- ``agent_runner`` -- tool-using agent (OpenAlex + Brave + SES + submit_experts)
  via ``resolve_provider()``; grounds OpenAlex ids and re-validates emails.
- ``web_search_tools`` -- Brave contact ``web_search`` for the agent path.
- ``openai_finder`` -- the OpenAI-backed finder variant (legacy path).
- ``openalex_tools`` -- works-first OpenAlex tools (``search_works`` + author
  lookup) with author/work grounding for the agent path.
- ``email_validation`` -- expert-finder email gate (role-local rejection,
  confidence thresholds, submit gate, agent tool) over
  ``mailing_list.EmailInsightsService``.
- ``json_parsing`` -- parsing/repair of the LLM's expert-list JSON output.
- ``persist`` -- upserts found experts and search memberships.
- ``source_enrichment`` -- post-persist LinkedIn/X/Google Scholar enrichment
  through Brave web search and Bedrock candidate matching.
- ``display`` -- display formatting of an ``Expert`` for listings and emails.
- ``progress`` -- Redis-backed progress publishing for the search UI.
- ``report_generator`` -- PDF/CSV report artifacts for a completed search.
"""
