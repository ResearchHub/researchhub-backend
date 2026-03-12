# ResearchHub Backend

Django REST API backend for ResearchHub - accelerating the pace of scientific research.

## Tech Stack
- **Framework**: Django 5+ + Django REST Framework
- **Python**: 3.13+
- **Database**: PostgreSQL
- **Search**: OpenSearch
- **Cache**: Redis
- **Task Queue**: Celery
- **Dependencies**: Managed with `uv`

## Project Structure
- `src/` - Main Django project directory
- Key apps: `paper`, `user`, `discussion`, `hub`, `search`, `feed`, `review`, `reputation`
- `src/config_local/` - Local configuration (db, keys)

## Common Commands
```bash
# Run server
cd src && python manage.py runserver

# Run tests (use --keepdb for faster local testing if there are no db changes)
python manage.py test --keepdb
python manage.py test <app_name> --exclude-tag=aws

# Run specific test
python manage.py test <app.tests.test_file.TestClass.test_method> --keepdb

# Celery (async tasks)
celery -A researchhub worker -l info -B

# OpenSearch indexing
python manage.py opensearch index rebuild

# Add dependencies
uv add <package_name>
```

## Development Guidelines
- Use Dev Containers (VSCode recommended)
- Run tests before committing
- Follow Django best practices
    - Move imports to top of file when possible
- Use DRF serializers and viewsets
- Keep migrations organized
- Tag AWS-dependent tests with `@tag('aws')`


## Testing
- Write failing test first
- Test behavior, not implementation
- Use Django's TestCase or DRF's APITestCase
- Mock external services (AWS, APIs)
- Exclude AWS tests locally: `--exclude-tag=aws`
