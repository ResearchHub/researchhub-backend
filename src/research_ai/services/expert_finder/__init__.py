"""Expert finder: the search pipeline that turns an RFP/query into experts.

- ``finder`` -- the ``ExpertFinderService`` pipeline and the
  ``run_expert_finder_search`` entry point.
- ``openai_finder`` -- the OpenAI-backed finder variant.
- ``json_parsing`` -- parsing/repair of the LLM's expert-list JSON output.
- ``persist`` -- upserts found experts and search memberships.
- ``display`` -- display formatting of an ``Expert`` for listings and emails.
- ``progress`` -- Redis-backed progress publishing for the search UI.
- ``report_generator`` -- PDF/CSV report artifacts for a completed search.
"""
