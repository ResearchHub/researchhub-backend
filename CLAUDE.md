# ResearchHub Backend

Django REST API backend for ResearchHub. The main application lives in `src/`.

## Environment
- Python 3.13
- Django 5.2 + Django REST Framework
- PostgreSQL, Redis, OpenSearch
- Celery for async work
- Dependencies managed with `uv`
- Dev Container is the preferred local setup

## Repository Layout
- `src/manage.py` - Django entrypoint
- `src/researchhub/` - project settings, URLs, and shared Django config
- `src/config_local/` - local config files and secrets
- Major domain apps include `paper`, `feed`, `discussion`, `hub`, `search`, `review`, `reputation`, `purchase`, `researchhub_document`, and `research_ai`

## Common Commands
Run Django commands from the repository root with `cd src && uv run python manage.py ...`.

```bash
# Run the API
cd src && uv run python manage.py runserver

# Database
cd src && uv run python manage.py migrate

# Tests
cd src && uv run python manage.py test --keepdb
cd src && uv run python manage.py test <app_name> --keepdb
cd src && uv run python manage.py test <app.tests.test_file.TestClass.test_method> --keepdb

# Search indexing
cd src && uv run python manage.py opensearch index rebuild

# Celery (development only)
cd src && uv run celery -A researchhub worker -l info -B

# Lint and formatting
cd src && uv run flake8
cd src && uv run black .
uv run pre-commit run --all-files

# Dependencies
uv add <package_name>
uv add --dev <package_name>
```

## Development Guidelines
- Prefer standard Django and DRF patterns.
- Keep imports at the top of the file when possible.
- Use serializers and viewsets for API boundaries.
- Keep business logic out of views when it can live in services or model-layer code.
- Keep migrations focused and reversible.
- Run the relevant tests before committing.

## Testing
- Prefer `django.test.TestCase` or DRF `APITestCase`.
- Mock external services instead of calling real integrations in unit tests.
- For AWS-dependent code, inherit from `AWSMockTestCase` in `src/utils/test_helpers.py`.
- Use `AWSMockTransactionTestCase` when the code under test relies on `transaction.on_commit()`.
- Test behavior, not implementation details.

## PR Philosophy: Optimize for Continuous Delivery

We optimize for continuous delivery with minimal gate-keeping. Trust in people and tooling over heavy process.

### Small PRs by Default
- Aim for ~100 lines or less per PR. Small enough for a human to understand in a few minutes.
- Write a brief, human-readable description of what changed and why.
- When working on large features, break the work into small incremental PRs using techniques like scaffolding and feature flags.
- Each PR should be a single logical change: one bug fix, one new endpoint, one refactor step.

### When Large PRs Are Acceptable
- Frontend changes where CSS/scaffolding naturally inflates line count.
- Refactoring work that touches many files in a mechanical way (renames, pattern migrations).
- Auto-generated code (migrations, schema dumps).

### What Matters
- Clarity over ceremony. A clear 5-line description beats a filled-out template.
- Tests should cover the change, but don't chase 100% coverage or fix unrelated lint warnings.
- Communicate what merged to the team. The PR description is the notification.
- If you're unsure about an approach, request review. Otherwise, trust the process.

### What Doesn't Matter
- Hitting an exact line count target. This is a guideline, not a KPI.
- Addressing every linter suggestion in files you didn't change.
- Getting human approval on every PR. Trust + tooling + communication is the model.

### AI-Assisted PRs
- AI can open PRs to fix specific bugs or vulnerabilities.
- AI PRs must include proof of work: screenshot, test output, or a short report.
- AI reviews check specific criteria (tests pass, no regressions, follows patterns).
- If criteria pass, AI can merge and notify the eng channel.

## CI Reference
CI runs from `src/` and performs:
- `uv run python manage.py migrate`
- `uv run python manage.py collectstatic --noinput`
- `uv run python manage.py opensearch index rebuild --force`
- `uv run coverage run manage.py test --verbosity=2`
