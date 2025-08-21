<p align="left">
    <h1 align="left">The <a aria-label="RH logo" href="https://researchhub.com">ResearchHub</a> API </h1>
</p>


<p align="left">

[![Automated Tests](https://github.com/ResearchHub/researchhub-backend-internal/actions/workflows/run-automated-tests.yml/badge.svg)](https://github.com/ResearchHub/researchhub-backend-internal/actions/workflows/run-automated-tests.yml)
</p>
<p align="left">&nbsp;</p>

# Our Mission
```
Our mission is to accelerate the pace of scientific research 🚀
```
We believe that by empowering scientists to independently fund, create, and publish academic content we can revolutionize the speed at which new knowledge is created and transformed into life-changing products.

# Important Links  👀
💡 Got an idea or request? [Open issue on Github](https://github.com/ResearchHub/researchhub-web/issues).  
🐛 Found a bug? [Report it here](https://github.com/ResearchHub/researchhub-web/issues).   
➕ Want to contribute to this project? [Introduce yourself in our Discord community](https://discord.gg/ZcCYgcnUp5)    
📰 Read the [ResearchCoin White Paper](https://www.researchhub.com/paper/819400/the-researchcoin-whitepaper)  
👷 [See what we are working on](https://github.com/orgs/ResearchHub/projects/3/views/3)


# Installation

The current recommended way to run this project is with [Dev Containers and VSCode](#dev-containers-and-vscode).

## Dev Containers and VSCode

### Prerequisites

Install [Docker](https://www.docker.com/), [Visual Studio Code](https://code.visualstudio.com/) and [the Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers). Please review the [Installation section](https://code.visualstudio.com/docs/devcontainers/containers#_installation) in the [Visual Studio Code Dev Container documentation](https://code.visualstudio.com/docs/devcontainers/containers).

On MacOS with [Homebrew](https://brew.sh/), the installation can be achieved with the following commands:

```shell
brew install docker
brew install visual-studio-code
code --install-extension ms-vscode-remote.vscode-remote-extensionpack
```

### Configuration

Clone the repository and create an initial configuration by copying the sample configuration files to `config_local`:

```shell
cp db_config.sample.py src/config_local/db.py
cp keys.sample.py src/config_local/keys.py
```

Make adjustments to the new configuration files as needed.

### Start Developing

When opening the code in VSCode, tt will recognize the Dev Containers configuration and will prompt to _Rebuild and Reopen in Container_.
Alternatively, select _Rebuild and Reopen in Container_ manually from the command palette.
This will pull and run all necessary auxiliary services including OpenSearch, PostgreSQL, and Redis.

During the creation of the dev container, all Python dependencies are downloaded and installed and an initial database migration is also performed. After dev container creation, proceed with [seeding the database](#Seed-the-database) as needed.

### Running and Debugging

Run the application by typing the following into integrated terminal:

```shell
cd src
python manage.py runserver
```

Alternatively, debugging of the application is possible with the following launch configuration (in `.vscode/launch.json`):

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
### OpenSearch
ResearchHub uses OpenSearch for search and browse. To index entities (users, papers, etc...) run:
```
python manage.py opensearch index rebuild
```


### Adding new packages

```shell
# add a package to the project environment
uv add package_name
```

### Testing

Run the test suite:

```shell
# run all tests
# Note: Add --keepdb flag to speed up the process of running tests locally
python manage.py test

# run tests for the paper app, excluding ones that require AWS secrets
python manage.py test paper --exclude-tag=aws

# run a specific test example:
run python manage.py test note.tests.test_note_api.NoteTests.test_create_workspace_note --keepdb
```

Run in the background for async tasks:

```shell
celery -A researchhub worker -l info
```

Run in the background for periodic tasks (needs celery running)

```shell
celery -A researchhub beat -l info
```

Both celery commands in one (for development only)

```shell
celery -A researchhub worker -l info -B
```

### Google Auth

Ask somebody to provide you with `CLIENT_ID` and `SECRET` config, and run this SQL query (with updated configs) to seed the right data for Google login to work:

```sql
insert into socialaccount_socialapp (provider, name, client_id, secret, key)
values ('google','Google','<CLIENT_ID>', '<SECRET>');

insert into django_site (domain, name) values ('http://google.com', 'google.com');

insert into socialaccount_socialapp_sites (socialapp_id, site_id) values (1, 1);
```

(make sure that IDs are the right one in the last query)
