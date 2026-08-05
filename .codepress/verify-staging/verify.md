# Staging verification

This backend repository contains local Dev Container infrastructure but no staging deployment command, cloud target, health URL, or deployment credentials.

The generated toolbox contains Python 3.13 with uv plus bash, curl, git, and jq. Its current command runs `uv sync --frozen --no-dev` as a safe locked-dependency check; it does not deploy or contact staging. No credentials are requested.

To enable real staging verification, replace `deploy_command`, add the required toolbox tools and non-AWS Agent Vault mappings, set `health_check.url`, and expand the verification contract with real deployed HTTP routes. Do not add secrets to this file or `recipe.json`.
