---
name: start-app-server
description: "Start the ResearchHub backend in Docker with PostgreSQL and Redis, then validate its health endpoint."
user_invocable: true
codepress_generated: true
---

# Start App Server — ResearchHub backend

Read `.codepress/start-app-server/recipe.json`. Compare the full `git hash-object Dockerfile.codepress` and `git hash-object pyproject.toml` values with the recorded checksums and report drift. Call `build_and_start_app_server` with `port: 8000`, `dockerfilePath: "Dockerfile.codepress"`, the recipe's static environment variables, and its `db` PostgreSQL and `cache` Redis services. The image runs Django migrations before Daphne, so allow up to 24 health polls on a fresh database.

Validate with `forward_app_request(containerId=<id>, path="/health/", method="GET")`; accept 200, 301, 302, or 404, preferring HTTP 200 with the database and cache rows marked working. Return the app container ID and leave the environment running unless asked to stop it.

This is a Django 5.2/uv backend. Development-only values in the recipe are safe placeholders; never add production credentials to the recipe.
