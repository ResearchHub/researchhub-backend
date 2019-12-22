# researchhub-backend

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
INFURA_RINKEBY_ENDPOINT = f'rinkeby.infura.io/v3/{INFURA_PROJECT_ID}'
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

### ELASTICSEARCH

In a new shell, run this Docker image script

```
./start-es.sh
```

Back in the python virtual environment, build the indices

```
python manage.py search_index --rebuild
```


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
```

### DEVELOPMENT

Some helpful commands for development:

```
python src/manage.py runserver
```
