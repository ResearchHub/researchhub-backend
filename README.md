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
🔨 [See what we are working on](https://github.com/orgs/ResearchHub/projects/2)   
📰 Read the [ResearchCoin White Paper](https://www.researchhub.com/paper/819400/the-researchcoin-whitepaper)  


# Installation

## 1. Quick install using Docker (Not recommended for development)

1. Download or clone this repository.
2. Copy local config files. From inside the dir root, run

```
cp db_config.sample.py src/config_local/db.py
cp keys.sample.py src/config_local/keys.py
cp twitter_config_sample.py src/config_local/twitter.py
```

3. Run:

```
docker build --tag researchhub-backend .
docker-compose up
```

The backend will now run at localhost:8000  
4. Setup and run the [web app](https://github.com/ResearchHub/researchhub-web) at localhost:3000

## 2. Native install (Slower, recommended for development)

### Prerequisites
1. Docker
2. pyenv
3. redis
4. Install the `flake8` linter in your IDE:
   - [vscode](https://code.visualstudio.com/docs/python/linting#_specific-linters)
   - [Sublime](https://github.com/SublimeLinter/SublimeLinter-flake8)
   - [flake8](http://flake8.pycqa.org/en/latest/index.html)

### General setup 

* Create a fork of the repository in your GitHub account, and clone it.

* Prepare the database:

    Create a db file in config

    ```shell
    touch src/config/db.py
    ```

    Add the following:

    ```python
    NAME = 'researchhub'
    HOST = 'localhost'
    PORT = 5432
    USER = 'rh_developer'  # replace as needed
    PASS = 'not_secure'  # replace as needed
    ```

    Create a local postgres db called `researchhub`. Alternatively, to use docker for local development (recommended), run the following:

    ```shell
    # https://docs.docker.com/samples/library/postgres/
    docker run \
    --rm \
    --name researchhub_db \
    --env POSTGRES_DB=researchhub \
    --env POSTGRES_USER=rh_developer \
    --env POSTGRES_PASSWORD=not_secure \
    --volume "$(pwd)"/database:/var/lib/postgresql/data \
    --publish 5432:5432 \
    --detach \
    postgres:12
    ```

  > Good UI tool for interacting with PostgreSQ: [Postico](https://eggerapps.at/postico2/)

* The project virtual environment is managed using [Poetry](https://python-poetry.org/docs/).
  ```shell
  pip3 install poetry
  ```

* Go to the [`src`](src) directory and run the following commands in order to activate the virtual environment:
    ```shell
    cd src

    # activates a Python virtual environment and enters shell
    poetry shell

    # installs the project virtual environment and packages
    poetry install
    ```

> The following commands should all be run in the virtual environment (`poetry shell`), in the [`src`](src) folder:

* Install python dependencies stored in `requirements.txt`:
  ```shell
  pip3 install -r requirements.txt --no-deps
  ```

* Create the database schema:

  ```shell
  python manage.py makemigrations
  python manage.py migrate
  ```

* The backend worker queue is managed using `redis`. Before you start the backend, in a separate terminal, run `redis-server`:
  ```shell
  brew install redis
  redis-server
  ```

* Start `celery`, the tool that runs the worker via `redis`. In a separate terminal:

  ```shell
  # celery: in poetry shell, run:
  cd src
  ./start-celery.sh
  ```

### Seed the database

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

   hub_df = pd.read_csv("../misc/hub_hub.csv")
   hub_df = hub_df.drop("slug_index", axis=1)
   hub_df = hub_df.drop("acronym", axis=1)
   hub_df = hub_df.drop("hub_image", axis=1)
   hubs = [Hub(**row.to_dict()) for _, row in hub_df.iterrows()]
   Hub.objects.bulk_create(hubs)
   ```

### Run the development server:

```shell
python manage.py runserver
```

### Ensure pre-commit hooks are set up
```
pre-commit install
```

## Useful stuff

#### Create a superuser in order to get data from the API

```shell
# create a superuser and retrieve an authentication token
python manage.py createsuperuser --username=florin --email=florin@researchhub.com
# p: not_secure
python manage.py drf_create_token florin@researchhub.com
```

#### Query the API using the Auth token 

> Note that for paths under `/api`, e.g. `/api/hub/`, you don't need a token.

```shell
curl --silent \
--header 'Authorization: Token <token>' \
http://localhost:8000/api/
```

#### Sending API requests via vscode

* Install the [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client) extension.

* Create a file called `api.rest` with the following contents (insert token):

   ```
   GET http://localhost:8000/api/ HTTP/1.1
   content-type: application/json
   Authorization: Token <token>
   ```

   Then press `Send Request` in vscode, above the text.

#### Seed paper data. 

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
python manage.py shell_plus # enters Python shell within poetry shell
```

```python
from paper.tasks import pull_crossref_papers, pull_papers
pull_crossref_papers(force=True)
pull_papers(force=True)
```

> **Make sure to revert that file once you're done seeding the local environment.**

#### Adding new packages

```shell
# add a package to the project environment
poetry add package_name

# update requirements.txt which is used by elastic beanstalk
poetry export -f requirements.txt --output requirements.txt
```

### ELASTICSEARCH (Optional)

In a new shell, run this Docker image script (make sure Redis is running in the background `redis-server`)

```
 # Let this run for ~30 minutes in the background before terminating, be patient :)
./start-es.sh
```

Back in the python virtual environment, build the indices

```
python manage.py search_index --rebuild
```

Optionally, start Kibana for Elastic dev tools

```
./start-kibana.sh
```

To view elastic queries via the API, add `DEBUG_TOOLBAR = True` to `keys.py`. Then, visit an API url such as [http://localhost:8000/api/search/paper/?publish_date\_\_gte=2022-01-01](http://localhost:8000/api/search/paper/?publish_date__gte=2022-01-01)

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

Make sure you have added the Infura keys (see above^)

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

#### Google Auth

Ask somebody to provide you with `CLIENT_ID` and `SECRET` config, and run this SQL query (with updated configs) to seed the right data for Google login to work:

```sql
insert into socialaccount_socialapp (provider, name, client_id, secret, key)
values ('google','Google','<CLIENT_ID>', '<SECRET>');

insert into django_site (domain, name) values ('http://google.com', 'google.com');

insert into socialaccount_socialapp_sites (socialapp_id, site_id) values (1, 1);
```

(make sure that IDs are the right one in the last query)
