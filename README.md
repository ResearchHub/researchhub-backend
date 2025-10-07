# The [ResearchHub](https://researchhub.com) API

[![Automated Tests](https://github.com/ResearchHub/researchhub-backend-internal/actions/workflows/run-automated-tests.yml/badge.svg)](https://github.com/ResearchHub/researchhub-backend-internal/actions/workflows/run-automated-tests.yml)

---

# 🚀 Our Mission 🚀

### Accelerate the pace of scientific research 

We believe that by empowering scientists to independently fund, create, and publish academic content we can revolutionize the speed at which new knowledge is created and transformed into life-changing products.

---

# 👀 Important Links 👀

💡 Got an idea or request? Found a bug? 🐛  [Open an issue on GitHub](https://github.com/ResearchHub/researchhub-backend/issues).  
➕ Want to contribute to this project? [Introduce yourself in our Discord community](https://discord.gg/ZcCYgcnUp5).  
📰 Read the [ResearchCoin White Paper](https://www.researchhub.com/paper/819400/the-researchcoin-whitepaper)  
👷 [See what we are working on](https://github.com/orgs/ResearchHub/projects/3/views/3)

---

# ⚙️ Installation ⚙️

## Prerequisites

- _(Optional, `macOS`)_ [Homebrew](https://brew.sh/) for simple installations using the `brew` command
- [Docker](https://www.docker.com/):
  ```shell
  brew install docker
  ```
- IDE with Dev Container support:
  - [VSCode](https://code.visualstudio.com/) _(Recommended)_:
    ```shell
    brew install visual-studio-code
    ```
    - Install extensions:
      - [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers):
        ```shell
        code --install-extension ms-vscode-remote.vscode-remote-extensionpack
        ```
  - [PyCharm](https://www.jetbrains.com/pycharm/)
    - Enable built-in plugins:
      - `Remote Development Gateway`
      - `Remote Execution Agent`
    - Install plugins:
      - [Docker](https://plugins.jetbrains.com/plugin/7724-docker)
      - [Dev Containers](https://plugins.jetbrains.com/plugin/21962-dev-containers)
    - Install [Gateway](https://www.jetbrains.com/remote-development/gateway/) for isolated remote IDE instance _(Recommended)_
- Database client
  - [Postico 2](https://eggerapps.at/postico2/) _(Recommended)_
  - [DataGrip](https://www.jetbrains.com/datagrip/)
    - Might be preferred if using PyCharm, since it's in the JetBrains ecosystem

## Setup

1. Copy the sample configuration files to `config_local`:
    ```shell
    cp db_config.sample.py src/config_local/db.py
    cp keys.sample.py src/config_local/keys.py
    ```
2. Launch Docker
   - You can safely close its window, its daemon will continue running in the background
3. Open the project in your IDE
   - It will recognize the Dev Container configuration and prompt to `Rebuild and Reopen in Container` (or `Reopen in Container`)
     - This will pull and run all necessary auxiliary services including OpenSearch, PostgreSQL, and Redis. It will also download and install all Python dependencies, and perform an initial database migration.
   - If the Dev Container's IDE instance doesn't automatically recognize the Python interpreter, point it to `.venv/bin/python`
4. Add the `PostgreSQL` database to your client
   - [Run the app](#run-the-app) to ensure the database is running
   - Name/User/Password/Database: `researchhub`
   - Host: `localhost`
   - Port: `5432`
   - Update `src/config_local/db.py` with the above values for parity

## Run the app

1. You can run the Dev Container's Django application one of two ways:
   - Directly in your IDE via its respective `Run` tool
   - Manually in the IDE's shell:
     ```shell
     cd src
     python manage.py runserver
     ```
2. The app will be available at http://localhost:8000
   - Or http://127.0.0.1:8000, depending on your setup
3. Test that the app is running by adding any random string to the end of the URL (ex: http://localhost:8000/abc)
   - If successful, you should see a `Page not found (404)` error page showing a list of the app's URL patterns
4. _(Optional)_ [Run Celery](#background-tasks) if you want to simulate background updates
   - Not generally needed or recommended because it can slow things down and clash with seeded DB data, but it can be useful when needing to replicate specific production features

## Seed the Database

1. Run any data migrations and ensure schemas are up to date:
   ```shell
   python src/manage.py migrate
   ```
2. Initialize Google auth, hub categories, and hubs:
   ```shell
   python src/manage.py setup
   ```
3. Load data from OpenAlex (institutions, topics, concepts, papers):
   ```shell
   python src/manage.py seed_all_openalex
   ```
4. Add additional research topic hubs:
   ```shell
   python src/manage.py seed_hubs_from_mappings
   ```
5. Initialize RSC exchange rate
   ```shell
   python src/manage.py refresh_exchange_rate
   ```
6. Populate research content (discussions, questions, hypotheses, pre-registrations with fundraises, journal papers, grants, bounties):
   ```shell
   python src/manage.py seed_all_research_content
   ```
7. Populate feed:
   ```shell
   python src/manage.py seed_all_feed
   ```
8. _(Optional, but recommended)_ Create a backup of the seeded data to easily restore it after running certain tests or other functions that wipe the DB:
   ```shell
   python src/manage.py manage_seeded_data_backup backup
   ```
   - To restore at a later time:
     ```shell
     python src/manage.py manage_seeded_data_backup restore
     ```

## Debugging

**VSCode**:
- Modify `.vscode/launch.json`:
  ```json
  {
    "version": "0.2.0",
    "configurations": [
      {
        "name": "Python: Django",
        "type": "debugpy",
        "request": "launch",
        "program": "${workspaceFolder}/src/manage.py",
        "args": ["runserver", "[::]:8000"],
        "django": true,
        "autoStartBrowser": false
      }
    ]
  }
  ```
**PyCharm**:
- Add a new `Django Server` run configuration:
  - Name: `Debug` (or whatever you want)
  - Host: `[::]`
  - Port: `8000`
  - Environment variables: `PYTHONUNBUFFERED=1;DJANGO_SETTINGS_MODULE=researchhub.settings`

---

## Testing

To run the test suite,`cd` into `src` first.  
Look for `OK` message at the end of each test.
- Run all tests (remove `--keepdb` to clean up the test database after each test, instead of keeping it around for faster testing):
  ```shell
  python manage.py test --keepdb
  ```
- Run tests for the paper app (excluding ones that require AWS secrets):
  ```shell
  python manage.py test paper --exclude-tag=aws
  ```
- Run a specific test example:
  ```shell 
  python manage.py test note.tests.test_note_api.NoteTests.test_create_workspace_note --keepdb
  ```

---

## Background Tasks

ResearchHub uses [Celery](https://github.com/celery/celery/) for background task processing.

- Start a worker that processes background tasks asynchronously:
  ```shell
  celery -A researchhub worker -l info
  ```
- Start a scheduler for periodic tasks like feed refreshes, bounty checks, etc. (above command must be running):
  ```shell
  celery -A researchhub beat -l info
  ```
- Both commands in one (local dev only)
  ```shell
  celery -A researchhub worker -l info -B
  ```

---

## Additional Commands

- After updating Django models, update the DB schema:
  ```shell
  python src/manage.py makemigrations
  python src/manage.py migrate
  ```
- Clear cache (useful when DB entries linger on the client even after they've been deleted):
  ```shell
  python src/manage.py shell -c "from django.core.cache import cache; cache.clear()"
  ```
  - Restart the app to see it reflected
- ResearchHub uses [OpenSearch](https://github.com/opensearch-project/OpenSearch) for search and browse. To index entities (users, papers, etc...) at any time, run:
  ```shell
  python src/manage.py opensearch index rebuild
  ```
- Wipe the DB so you can [reseed](#seed-the-database) from scratch:
  ```shell
  python src/manage.py flush --noinput
  ```
- Add new Python packages:

  ```shell
  uv add package_name
  ```

---

## Additional Information
- Dev Container's Django app
  - If it's running when repository changes are pulled, you'll need to restart the app for the changes to take effect
  - Rebuilding the Dev Container is only necessary when something changes that affects the image (uncommon), such as changes to the `Dockerfile`, `docker-compose.yml`, or `devcontainer.json`

---

## Troubleshooting

**VSCode**:
- Nothing yet!

**PyCharm**:
- If your Dev Container launches but doesn't activate any ports (you don't see port numbers listed next to the containers in `Docker`):
  1. Stop and delete all containers, volumes, and images in `Docker`
  2. Create or update `.devcontainer/docker-compose.local.yml`:
     ```yaml
     services:
     postgres:
       ports: ["5432:5432"]
     redis:
       ports: ["6379:6379"]
     opensearch:
       ports: ["9200:9200"]
     opensearch-dashboards:
       ports: ["5601:5601"]
     app:
        ports: ["8000:8000"]
     ```
  3. Manually initialize the `Docker` containers:
     ```shell
     docker compose -f .devcontainer/docker-compose.yml -f .devcontainer/docker-compose.local.yml up -d
     ```
  4. Open your IDE back up and try launching the Dev Container again

---

## Next Steps

You've completed the hardest part – time to set up the [frontend](https://github.com/ResearchHub/web#readme) web interface! 🎉
