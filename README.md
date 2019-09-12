# researchhub-backend

## Setup

### GENERAL

Create a keys file in config

`$ touch src/config/keys.py`

Add the secret key

`SECRET_KEY='secretkey'`

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

