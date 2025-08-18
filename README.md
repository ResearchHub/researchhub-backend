<p align="left">
    <h1 align="left">The <a aria-label="RH logo" href="https://researchhub.com">ResearchHub</a> Django API </h1>
</p>


<p align="left">

[![Automated Tests](https://github.com/ResearchHub/researchhub-backend-internal/actions/workflows/run-automated-tests.yml/badge.svg)](https://github.com/ResearchHub/researchhub-backend-internal/actions/workflows/run-automated-tests.yml)
  <a aria-label="Join the community" href="https://researchhub-community.slack.com">
    <img alt="" src="https://badgen.net/badge/Join%20the%20community/Slack/yellow?icon=slack">
  </a>
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
This will pull and run all necessary auxiliary services including ElasticSearch, PostgreSQL, and Redis.

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

## Seed the database

* In order for the UI to work properly, some data needs to be seeded into the database. Seed category data:

    ```shell
    python manage.py create-categories
    ```

* Seed hub data. There's a CSV file in `/misc/hub_hub.csv` with hub data that you can use to seed hubs data. This can be done in two ways:

    * in `Postico`: right-click on the `hub_hub` table, and select `Import CSV...`. You will encounter problems importing the CSV due to the tool thinking that empty fields are nulls for `acronym` and `description` columns. Temporarily update `hub_hub` table to allow null values for those columns:
   ```postgresql
   ALTER TABLE hub_hub ALTER COLUMN description DROP NOT NULL;
   ALTER TABLE hub_hub ALTER COLUMN acronym DROP NOT NULL;
   ```
   Import CSV, then change all nulls to empty in the two columns, and revert the columns to not null:

   ```postgresql
   UPDATE hub_hub set acronym='', description='';
   ALTER TABLE hub_hub ALTER COLUMN description SET NOT NULL;
   ALTER TABLE hub_hub ALTER COLUMN acronym SET NOT NULL;
   ```
   **OR**
   * in Python: run `python manage.py shell_plus` to open a Python terminal in the virtual environment. Then, paste the following code:

```python
import pandas as pd
from hub.models import Hub

hub_df = pd.read_csv("../misc/hub_hub.csv")
hub_df = hub_df.drop("slug_index", axis=1)
hub_df = hub_df.drop("acronym", axis=1)
hub_df = hub_df.drop("hub_image", axis=1)
hubs = [Hub(**row.to_dict()) for _, row in hub_df.iterrows()]
Hub.objects.bulk_create(hubs)
```

## Useful stuff

### Ensure pre-commit hooks are set up
```
pre-commit install
```

### Create a superuser in order to get data from the API

```shell
# create a superuser and retrieve an authentication token
python manage.py createsuperuser --username=florin --email=florin@researchhub.com
# p: not_secure
python manage.py drf_create_token florin@researchhub.com
```

### Query the API using the Auth token 

> Note that for paths under `/api`, e.g. `/api/hub/`, you don't need a token.

```shell
curl --silent \
--header 'Authorization: Token <token>' \
http://localhost:8000/api/
```

### Sending API requests via vscode

* Install the [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client) extension.

* Create a file called `api.rest` with the following contents (insert token):

   ```
   GET http://localhost:8000/api/ HTTP/1.1
   content-type: application/json
   Authorization: Token <token>
   ```

   Then press `Send Request` in vscode, above the text.

### Seed paper data. 

> For this to work, the celery worker needs to be running (see above). This calls two methods that are temporarily disabled, in [`src/paper/tasks.py`](src/paper/tasks.py): `pull_crossref_papers()` and `pull_papers()`. First, comment the first line of the methods, that cause the methods to be disabled. Then, change the `while` loops to finish after pulling a small number of papers (enough to populate local environment):

```python
def pull_papers(start=0, force=False):
    # Temporarily disabling autopull
    return  # <-- this line needs to be commented out
    ...
    while True:  # <-- change this to while i < 100:

...

def pull_crossref_papers(start=0, force=False):
    # Temporarily disabling autopull
    return  # <-- this line needs to be commented out
    ...
    while True:  # <-- change this to while offset < 100:
```

Then, run:
```shell
python manage.py shell_plus
```

```python
from paper.tasks import pull_crossref_papers, pull_papers
pull_crossref_papers(force=True)
pull_papers(force=True)
```

> **Make sure to revert that file once you're done seeding the local environment.**

### Adding new packages

```shell
# add a package to the project environment
uv add package_name
```

### ETHEREUM (Optional)

Create a wallet file in config

```
touch src/config/wallet.py
```

Add the following to wallet.py (fill in the blanks)

```python
KEYSTORE_FILE = ''
KEYSTORE_PASSWORD = ''
```

Add the keystore file to the config directory

> Ask a team member for the file or create one from MyEtherWallet
> https://www.myetherwallet.com/create-wallet

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
