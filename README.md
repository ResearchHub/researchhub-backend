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

Create a local postgres db called `researchhub`

### ELASTICSEARCH

EASY RUN: `./start-es.sh`



In a new shell, pull the Elasticsearch docker image

`$ docker pull docker.elastic.co/elasticsearch/elasticsearch:7.4.1`

Then run a basic development cluster

`$ docker run -p 9200:9200 -p 9300:9300 -e "discovery.type=single-node" docker.elastic.co/elasticsearch/elasticsearch:7.4.1`

Back in the python virutal environment, build the indices

`$ python manage.py search_index --rebuild`
