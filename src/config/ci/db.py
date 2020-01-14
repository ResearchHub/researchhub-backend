from . import get_env_var

NAME = 'researchhub'
HOST = get_env_var('DB_HOST', 'localhost')
PORT = get_env_var('DB_PORT', 5432)
USER = get_env_var('DB_USER', 'rh_developer')
PASS = get_env_var('DB_USER', 'not_secure')
