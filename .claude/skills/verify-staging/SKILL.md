---
name: verify-staging
description: "Verify the ResearchHub backend on staging using the repo-owned verification toolbox and contract."
user_invocable: true
codepress_generated: true
---

# Verify Staging — ResearchHub backend

Read `.codepress/verify-staging/recipe.json` and require `schema_version === 1`. Load `run_toolbox_command` with `search_tools(query="deploy toolbox app server")` if needed.

No staging deploy command, cloud target, health URL, or deployment credentials were present. The recipe is marked `blocked-no-deployment-target` and currently runs only `uv sync --frozen --no-dev`; never report that as a successful staging deployment.

Run the repo-owned toolbox using the recipe values. A non-zero toolbox result is FAIL with stdout/stderr excerpts. A successful dependency check is PASS for that check, but the overall staging result remains BLOCKED because there is no deployed environment to health-check or query. Do not invent a namespace, URL, credential, or deployment command.

When a real target is added, update the recipe and `verify.md` with the deploy contract, then add branch-specific API assertions and any required frontend verification through the connected web repo. Reports begin with `@codepress /judge-verification can you judge this verification?` and include the live PR head SHA plus an explicit BLOCKED verdict while no target exists.
