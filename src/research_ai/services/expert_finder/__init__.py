"""Expert finder: search pipeline from a research description into experts.

The description may come from a grant/RFP, proposal/preregistration, paper,
or free-form query; outreach role (collaborator vs reviewer) is chosen later.

- ``finder`` -- the ``ExpertFinderService`` pipeline and the
  ``run_expert_finder_search`` entry point.
- ``find_more_service`` -- lock, validate, enqueue, and roll back find-more
  (append) runs.
- ``agent_runner`` -- tool-using agent (OpenAlex + Brave + SES + submit_experts)
  via ``resolve_provider()``; grounds OpenAlex ids, hard-filters region,
  accumulates until the target count, and re-validates emails.
- ``region_filter`` -- Region → ISO country codes and author match helpers.
- ``web_search_tools`` -- Brave contact ``web_search`` for the agent path.
- ``work_email_lookup`` -- affiliation emails from OpenAlex, with Europe PMC /
  Crossref only when OpenAlex has none (no HTML scrape).
- ``openai_finder`` -- legacy OpenAI Responses path (unused by the live finder).
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
- ``events`` -- Channels WebSocket progress / experts_found publishing.
- ``report_generator`` -- PDF/CSV report artifacts for a completed search.
"""
