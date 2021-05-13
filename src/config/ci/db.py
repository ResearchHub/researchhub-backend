import os

NAME = 'researchhub'
HOST = os.environ.get('DB_HOST', 'localhost')
PORT = os.environ.get('DB_PORT', '5432')
USER = os.environ.get('DB_USER', 'rh_developer')
PASS = os.environ.get('DB_USER', 'not_secure')
