# researchhub-backend

## Setup

### GENERAL

Install the `flake8` linter in your IDE

VSCODE - https://code.visualstudio.com/docs/python/linting#_specific-linters
Sublime - https://github.com/SublimeLinter/SublimeLinter-flake8
flake8 - http://flake8.pycqa.org/en/latest/index.html

Create a keys file in config

`$ touch src/config/keys.py`

Add the following to keys.py (fill in the blanks)

```python
SECRET_KEY = ''
AWS_ACCESS_KEY_ID = ''
AWS_SECRET_ACCESS_KEY = ''
INFURA_PROJECT_ID = ''
INFURA_PROJECT_SECRET = ''
INFURA_RINKEBY_ENDPOINT = f'rinkeby.infura.io/v3/{INFURA_PROJECT_ID}'
```

Set executable permissions on scripts

`$ chmod -R u+x scripts/`

Install git hooks

`$ ./scripts/install-hooks`

### DATABASE

Create a db file in config

`$ touch src/config/db.py`

Add the following

```python

NAME = 'researchhub'
HOST = 'localhost'
PORT = 5432
USER = ''
PASS = ''

```

Create a local postgres db called `researchhub`

### ELASTICSEARCH

In a new shell, run this Docker image script

`$ ./start-es.sh`

Back in the python virutal environment, build the indices

`$ python manage.py search_index --rebuild`
