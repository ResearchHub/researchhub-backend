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

## CI Reference
CI runs from `src/` and performs:
- `uv run python manage.py migrate`
- `uv run python manage.py collectstatic --noinput`
- `uv run python manage.py opensearch index rebuild --force`
- `uv run coverage run manage.py test --verbosity=2`
