# researchhub-backend

[![GitHub Actions Status Badge](https://github.com/ResearchHub/researchhub-backend/workflows/Backend%20CI/badge.svg?branch=master)](https://github.com/ResearchHub/researchhub-backend/actions)

This repository contains the Django backend for <https://www.researchhub.com/>.

## Setup

### GENERAL

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

Set executable permissions on scripts

```
chmod -R u+x scripts/
```

Install git hooks

```
./scripts/install-hooks
```

### DATABASE

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
To use docker for local development, run the following:

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

### ENVIRONMENT

The project environment is managed using [Pipenv](https://pipenv.kennethreitz.org/en/latest/).
Run the following commands from the [`src`](src) directory:

```shell
# install the project environment
pipenv install

# activate the environment
pipenv shell

# add a package to the project environment
pipenv install package_name

# update requirements.txt which is used by elastic beanstalk
pipenv lock --requirements >| requirements.txt
```

### ELASTICSEARCH

In a new shell, run this Docker image script (make sure Redis is running in the background ```redis-server```) 

```
 # Let this run for ~30 minutes in the background before terminating, be patient :)
./start-es.sh
```

Back in the python virtual environment, build the indices

```
python manage.py search_index --rebuild
```
-------

### ETHEREUM

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

Update the database schema:

```shell
python src/manage.py makemigrations
python src/manage.py migrate
```

Run a development server and make the API available at <http://localhost:8000/api/>:

```shell
# create a superuser and retrieve an authentication token
python src/manage.py createsuperuser --username=<username> --email=<email>
python src/manage.py drf_create_token <email>

# run the development server
python src/manage.py runserver

# query the API
curl --silent \
  --header 'Authorization: Token <token>' \
  http://localhost:8000/api/
```

Run the test suite:

```shell
# run all tests
python manage.py test

# run tests for the paper app, excluding ones that require AWS secrets
python manage.py test paper --exclude-tag=aws
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
