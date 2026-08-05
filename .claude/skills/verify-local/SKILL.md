---
name: verify-local
description: "Verify the ResearchHub backend locally by starting its bootstrapped Django container and running HTTP contract checks."
user_invocable: true
codepress_generated: true
---

# Verify Local — ResearchHub backend

Read `.codepress/start-app-server/recipe.json`, then call `Skill({"skill":"start-app-server"})`. Use the returned container ID with `forward_app_request`; do not hand-start Django or mock services.

## Default contract

| Name | Method | Path | Expected | Proves |
| --- | --- | --- | --- | --- |
| health | GET | `/health/` | 200 | Django, PostgreSQL, and Redis are reachable and the health backends report working. |
| admin login | GET | `/admin/login/` | 200 | The public Django admin authentication surface renders. |
| missing route | GET | `/__codepress_missing_route__` | 404 | URL routing returns a real negative response. |

Inspect `git diff` against the default branch before execution and add assertions for every changed API route, permission boundary, and persisted behavior. No test account or auth bypass was discoverable, so authenticated endpoints remain uncovered unless credentials are supplied at runtime. Any changed behavior outside live HTTP coverage stays `FAIL` in the report. Prefix reports with `@codepress /judge-verification can you judge this verification?` and stop the container after validation unless an open-PR workflow owns it.

Bootstrap note: fresh environments run more than 1,000 Django migrations before `/health/` becomes ready; the recipe records an extended polling window.
