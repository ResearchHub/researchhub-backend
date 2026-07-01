# ResearchHub Backend

Django REST API backend for ResearchHub. The main application lives in `src/`.

## Environment
- Python 3.13
- Django 5.2 + Django REST Framework
- PostgreSQL, Redis, OpenSearch
- Celery for async work
- Dependencies managed with `uv`
- Linting and formatting is done with `ruff`
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
uv run ruff check src
uv run ruff format --check --diff src
uv run pre-commit run --all-files

# Dependencies
uv add <package_name>
uv add --dev <package_name>
```

## Development Guidelines
- Prefer standard Django and DRF patterns.
- Keep imports at the top of the file when possible.
- Use serializers and viewsets for API boundaries.
- Keep migrations focused and reversible.
- Run the relevant tests before committing.

## Code Placement
New code belongs to a layer and to the app that owns the domain. Decide both
before writing it.

### Pick the owning app first
- Logic that operates on a domain lives in that domain's app, not in a shared
  catch-all. Paper logic goes in `paper`, reputation/fee logic in `reputation`,
  payments/funding in `purchase`, AI/LLM work in `research_ai`, and so on.
- `src/utils/` is only for genuinely cross-app, framework-level helpers
  (HTTP, AWS, parsing, locking, time). Do not add domain logic there; if a
  helper knows about a specific app's models or rules, it belongs in that app.

### Pick the layer
- **Views** (`{app}/views/`) — HTTP concerns only. Delegate real work to a
  service or model; no business logic here.
- **Services** (`{app}/services/*_service.py`) — the default home for business
  logic: multi-step operations, calculations, validation, transactions, and
  external-API/integration calls. This is where most new non-trivial logic
  should go.
- **Models / managers** (`{app}/models.py`, `models/`, or `related_models/`) —
  persistence and thin domain methods/querysets that operate on a single record
  or query. Keep cross-entity orchestration out of models; put it in a service.
- **Tasks** (`{app}/tasks.py` or `tasks/`) — Celery entry points and retry
  handling only. The actual work they perform should live in a service the task
  calls.
- **Signals** (`{app}/signals.py`) — event wiring and lightweight side effects;
  defer heavy work to a service or task.

### Service conventions
- Accept dependencies (clients, other services) via the constructor so they can
  be mocked in tests; default them to the real implementation.

## Testing
- If possible, use `unittest.TestCase` when there is no dependency on Django, otherwise use `django.test.TestCase` or DRF `APITestCase`.
- Mock external services instead of calling real integrations in unit tests.
- For AWS-dependent code, inherit from `AWSMockTestCase` in `src/utils/test_helpers.py`.
- Use `AWSMockTransactionTestCase` when the code under test relies on `transaction.on_commit()`.
- Test behavior, not implementation details.
- Add Arrange/Act/Assert (AAA) comment markers to tests.
- Prefer `patch.object()` when patching on classes already imported into the test module.
  Use string-based `patch("module.path.symbol")` when the test needs to replace the exact 
  symbol that the code under test imports or accesses at runtime.

## CI Reference
CI runs from `src/` and performs:
- `uv run python manage.py migrate`
- `uv run python manage.py collectstatic --noinput`
- `uv run python manage.py opensearch index rebuild --force`
- `uv run coverage run manage.py test --verbosity=2`
