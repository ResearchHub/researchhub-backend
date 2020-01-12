from . import get_env_var


SECRET_KEY = 'development'
AWS_ACCESS_KEY_ID = get_env_var('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = get_env_var('AWS_SECRET_ACCESS_KEY')
INFURA_PROJECT_ID = get_env_var('INFURA_PROJECT_ID')
INFURA_PROJECT_SECRET = get_env_var('INFURA_PROJECT_SECRET')
INFURA_RINKEBY_ENDPOINT = f'https://rinkeby.infura.io/v3/{INFURA_PROJECT_ID}'
