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

## Our Mission
```
Our mission is to accelerate the pace of scientific research 🚀
```
We believe that by empowering scientists to independently fund, create, and publish academic content we can revolutionize the speed at which new knowledge is created and transformed into life-changing products.

## Important Links  👀
💡 Got an idea or request? [Create a discussion on Github](https://github.com/ResearchHub/researchhub-web-internal/discussions/categories/ideas-and-requests).  
❓ Got a question? [Ask it here](https://github.com/ResearchHub/researchhub-web-internal/discussions/categories/q-a)  
🐛 Found a bug? [Report it here](https://github.com/ResearchHub/researchhub-web-internal/discussions/categories/bugs)  
💰 Earn ResearchCoin (RSC) by [completing bounties](https://github.com/ResearchHub/researchhub-web/issues?q=is%3Aopen+is%3Aissue+label%3Abounty)  
🙌 Want to work with us? [View our open positions](https://www.notion.so/researchhub/Working-at-ResearchHub-6e0089f0e234407389eb889d342e5049)  
➕ Want to contribute to this project? [Introduce yourself in our Slack community](https://researchhub-community.slack.com)  
📰 Read the [ResearchCoin White Paper](https://www.researchhub.com/paper/819400/the-researchcoin-whitepaper)  

## Installation
### 1. Quick install using Docker (Recommended)

1. Clone this repository. Inside the directory, run
```
docker build --tag researchhub-backend .
docker-compose up
```
The backend will now run at localhost:8000  
2. Setup and run the [web app](https://github.com/ResearchHub/researchhub-web) at localhost:3000 

### 2. Native install (Slower, not recommended)

#### General

Install the `flake8` linter in your IDE

- [vscode](https://code.visualstudio.com/docs/python/linting#_specific-linters)
- [Sublime](https://github.com/SublimeLinter/SublimeLinter-flake8)
- [flake8](http://flake8.pycqa.org/en/latest/index.html)

Create a keys file in config

```
touch src/config/keys.py
```

Add the following to `keys.py` (fill in the blanks)

```python
SECRET_KEY = ''
AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
INFURA_PROJECT_ID = ''
INFURA_PROJECT_SECRET = ''
INFURA_RINKEBY_ENDPOINT = f'https://rinkeby.infura.io/v3/{INFURA_PROJECT_ID}'
```

Add local config files by copying files from `src/config` to `src/config_local`. Ask somebody to provide all the keys.

Set executable permissions on scripts

```
chmod -R u+x scripts/
```

Install git hooks

```
./scripts/install-hooks
```

#### DATABASE

Create a db file in config

```shell
touch src/config/db.py
```

Add the following

```python
NAME = 'researchhub'
HOST = 'localhost'
PORT = 5432
USER = 'rh_developer' # replace as needed
PASS = 'not_secure'   # replace as needed
```

Create a local postgres db called `researchhub`.
Alternatively, to use docker for local development, run the following:

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

#### ENVIRONMENT

The project environment is managed using [Poetry](https://python-poetry.org/docs/).

The project uses Python version 3.8, so you will need to install it (use pyenv e.g.)

If you're installing on macOS 11.x, additional step is required for which the explanation can be found [here](https://stackoverflow.com/questions/66482346/problems-installing-python-3-6-with-pyenv-on-mac-os-big-sur) or [here](https://docs.google.com/document/d/1tObZtc_GLf1h2OY9Ig6LjYub5zNMARG_ge3pUXKV3HI/edit?usp=sharing), that basically installs the right version of Python with extra flags (notice Python version within the script):

```
CFLAGS="-I$(brew --prefix openssl)/include -I$(brew --prefix bzip2)/include -I$(brew --prefix readline)/include -I$(xcrun --show-sdk-path)/usr/include" LDFLAGS="-L$(brew --prefix openssl)/lib -L$(brew --prefix readline)/lib -L$(brew --prefix zlib)/lib -L$(brew --prefix bzip2)/lib" pyenv install --patch 3.8.12 < <(curl -sSL https://github.com/python/cpython/commit/8ea6353.patch\?full_index\=1)
```

After installing Python, run the following commands from the [`src`](src) directory:

```shell
# installs the project environment and packages
poetry install

# activates the environment and enters shell
poetry shell
```

In general, when adding new packages, follow these steps:

```shell
# add a package to the project environment
poetry add package_name

# update requirements.txt which is used by elastic beanstalk
poetry export -f requirements.txt --output requirements.txt
```

#### REDIS (Required)

Make sure to run `redis-server` in a separate terminal.

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

### DEVELOPMENT

This sections contains some helpful commands for development.

> Run these from within `poetry shell` from `src`, like it was previously mentioned.

Update the database schema:

```shell
python manage.py makemigrations
python manage.py migrate
```

Run a development server and make the API available at <http://localhost:8000/api/>:

```shell
# create a superuser and retrieve an authentication token
python manage.py createsuperuser --username=<username> --email=<email>
python manage.py drf_create_token <email>

# run the development server
python manage.py runserver

# query the API
curl --silent \
  --header 'Authorization: Token <token>' \
  http://localhost:8000/api/
```

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

---

#### Google Auth

Ask somebody to provide you with `CLIENT_ID` and `SECRET` config, and run this SQL query (with updated configs) to seed the right data for Google login to work:

```sql
insert into socialaccount_socialapp (provider, name, client_id, secret, key)
values ('google','Google','<CLIENT_ID>', '<SECRET>');

insert into django_site (domain, name) values ('http://google.com', 'google.com');

insert into socialaccount_socialapp_sites (socialapp_id, site_id) values (1, 1);
```

(make sure that IDs are the right one in the last query)

#### Seeding hub data

There's a CSV file in `/misc/hub_hub.csv` with hub data that you can use to seed hubs data.

> If you encounter problems importing CSV due to DB tool thinking that empty fields are nulls for `acronym` and `description` columns, temporarily update `hub_hub` table to allow null values for those columns, import CSV, then execute `update hub_hub set acronym='', description='';` to populate with non-null yet empty values, then update table to disallow nulls again.

Then run this from `poetry shell`:

```shell
python manage.py create-categories
python manage.py migrate-hubs
python manage.py categorize-hubs
```

#### Seeding paper data

From your terminal, follow these steps:

```shell
cd src
poetry shell
python manage.py shell_plus # enters Python shell within poetry shell

from paper.tasks import pull_crossref_papers, pull_papers
pull_crossref_papers()
pull_papers()
```
