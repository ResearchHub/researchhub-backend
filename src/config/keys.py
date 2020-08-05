import os

SECRET_KEY = os.environ.get('SECRET_KEY', 'development')

AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')

INFURA_PROJECT_ID = os.environ.get('INFURA_PROJECT_ID', '')
INFURA_PROJECT_SECRET = os.environ.get('INFURA_PROJECT_SECRET', '')
INFURA_RINKEBY_ENDPOINT = f'https://rinkeby.infura.io/v3/{INFURA_PROJECT_ID}'

MAILCHIMP_KEY = os.environ.get('MAILCHIMP_KEY')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')
