"""
Django settings for researchhub project.

Generated by 'django-admin startproject' using Django 2.2.5.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""

import os
import requests
import sys
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_ENV = os.environ.get('APP_ENV') or 'development'
DEVELOPMENT = APP_ENV == 'development'
PRODUCTION = APP_ENV == 'production'
STAGING = APP_ENV == 'staging'
CI = "GITHUB_ACTIONS" in os.environ
CLOUD = PRODUCTION or STAGING or CI
TESTING = ('test' in APP_ENV) or ('test' in sys.argv)
PYTHONPATH = '/opt/python/current/app:$PYTHONPATH'
DJANGO_SETTINGS_MODULE = 'researchhub.settings'
ELASTIC_BEANSTALK = (APP_ENV in ['production', 'staging', 'development'])

if CLOUD:
    CONFIG_BASE_DIR = 'config'
    from config import db, keys, wallet
else:
    CONFIG_BASE_DIR = 'config_local'
    from config_local import db, keys, wallet

if DEVELOPMENT:
    BASE_FRONTEND_URL = 'http://localhost:3000'
elif PRODUCTION:
    BASE_FRONTEND_URL = 'https://researchhub.com'
elif CLOUD:
    BASE_FRONTEND_URL = 'https://staging-web.researchhub.com'

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', keys.SECRET_KEY)

# python manage.py check --deploy
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
if not (PRODUCTION or STAGING):
    DEBUG = True

ALLOWED_HOSTS = [
    '.quantfive.org',
    '.elasticbeanstalk.com',
    '.researchhub.com',
    'localhost'
]

if not (PRODUCTION or STAGING):
    ALLOWED_HOSTS += [
        '.ngrok.io',
        'localhost',
        '10.0.2.2',
        '10.0.3.2'
    ]

if ELASTIC_BEANSTALK:
    try:
        ALLOWED_HOSTS.append(
            requests.get('http://169.254.169.254/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        ALLOWED_HOSTS.append(
            requests.get('http://172.31.19.162/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        ALLOWED_HOSTS.append(
            requests.get('http://54.200.83.4/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        # Production private ips
        ALLOWED_HOSTS.append(
            requests.get('http://172.31.0.82/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        ALLOWED_HOSTS.append(
            requests.get('http://172.31.9.43/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        # Staging private ips
        ALLOWED_HOSTS.append(
            requests.get('http://172.31.8.17/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        ALLOWED_HOSTS.append(
            requests.get('http://172.31.6.81/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
        ALLOWED_HOSTS.append(
            requests.get('http://172.31.5.32/latest/meta-data/local-ipv4',
                         timeout=0.01).text)
    except requests.exceptions.RequestException:
        pass


# Cors

CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",
    'https://dev.researchhub.com',
    'https://researchnow.researchhub.com',
    'https://www.researchhub.com',
    'https://staging-web.researchhub.com',
    'https://researchhub.com'
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.sites',
    'django.contrib.staticfiles',
    'django_filters',

    # https://github.com/django-extensions/django-extensions
    'django_extensions',

    # CORS
    'corsheaders',

    # Postgres
    'django.contrib.postgres',

    # Rest framework
    'rest_framework',

    # Authentication
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.orcid',
    'rest_framework.authtoken',
    'rest_auth',
    'rest_auth.registration',

    # Storage
    'storages',

    # Search
    'django_elasticsearch_dsl',
    'django_elasticsearch_dsl_drf',

    # Emails
    'django_ses',
    'django_inlinecss',

    # Custom apps
    'discussion',
    'ethereum',
    'hub',
    'mailing_list',
    'oauth',
    'paper',
    'reputation',
    'search',
    'summary',
    'user',
]

SITE_ID = 1

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'researchhub.middleware.csrf_disable.DisableCSRF',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if not CLOUD:
    INSTALLED_APPS += [
        'silk',
        'dbbackup'
    ]

    MIDDLEWARE += [
        'silk.middleware.SilkyMiddleware',
    ]

    DBBACKUP_STORAGE = 'django.core.files.storage.FileSystemStorage'
    DBBACKUP_STORAGE_OPTIONS = {'location': 'backups'}

ROOT_URLCONF = 'researchhub.urls'

FILE_UPLOAD_MAX_MEMORY_SIZE = 26214400  # 25MB max data allowed

PAGINATION_PAGE_SIZE = 20

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
        # 'rest_framework.permissions.AllowAny',  # FOR TESTING ONLY
    ],
    'DEFAULT_PAGINATION_CLASS':
        'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': PAGINATION_PAGE_SIZE,
    'TEST_REQUEST_RENDERER_CLASSES': [
        'rest_framework.renderers.MultiPartRenderer',
        'rest_framework.renderers.JSONRenderer',
        'utils.renderers.PlainTextRenderer',
    ],
}


TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'researchhub.wsgi.application'


# Authentication

AUTH_USER_MODEL = 'user.User'

AUTHENTICATION_BACKENDS = (
    # Needed to login by username in Django admin, regardless of `allauth`
    'django.contrib.auth.backends.ModelBackend',
    # `allauth` specific authentication methods, such as login by e-mail
    'allauth.account.auth_backends.AuthenticationBackend',
)

OAUTH_METHOD = 'token'

REST_AUTH_REGISTER_SERIALIZERS = {
    'REGISTER_SERIALIZER': 'user.serializers.RegisterSerializer',
}

GOOGLE_REDIRECT_URL = 'http://localhost:8000/auth/google/login/callback/'
if PRODUCTION:
    GOOGLE_REDIRECT_URL = (
        'https://backend.researchhub.com/auth/google/login/callback/'
    )
if STAGING:
    GOOGLE_REDIRECT_URL = (
        'https://staging-backend.researchhub.com/auth/google/login/callback/'
    )

# Django AllAuth setup
# https://django-allauth.readthedocs.io/en/latest/configuration.html

ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USERNAME_REQUIRED = False
LOGIN_REDIRECT_URL = '/api'
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_EMAIL_REQUIRED = False
SOCIALACCOUNT_QUERY_EMAIL = True

SOCIALACCOUNT_PROVIDERS = {
    'orcid': {
        'APP': {
            'name': 'Orcid',
            'client_id': keys.ORCID_CLIENT_ID,
            'secret': keys.ORCID_CLIENT_SECRET,
            'sites': 1,
        },
        # Defaults to 'orcid.org' for the production API
        'BASE_DOMAIN': 'orcid.org',  # for the sandbox API
        'MEMBER_API': False,  # Defaults to False for the Public API
    }
}

ORCID_REDIRECT_URL = 'http://localhost:8000/auth/orcid/login/callback/'
if PRODUCTION:
    ORCID_REDIRECT_URL = (
        'https://backend.researchhub.com/auth/orcid/login/callback/'
    )
if STAGING:
    ORCID_REDIRECT_URL = (
        'https://staging-backend.researchhub.com/auth/orcid/login/callback/'
    )

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

DB_NAME = os.environ.get('DB_NAME', db.NAME)
DB_HOST = os.environ.get('DB_HOST', db.HOST)
DB_PORT = os.environ.get('DB_PORT', db.PORT)
DB_USER = os.environ.get('DB_USER', db.USER)
DB_PASS = os.environ.get('DB_PASS', db.PASS)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': DB_NAME,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
        'USER': DB_USER,
        'PASSWORD': DB_PASS,
    },
}


# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': ('django.contrib.auth.password_validation.'
                 'UserAttributeSimilarityValidator'),
    },
    {
        'NAME': ('django.contrib.auth.password_validation.'
                 'MinimumLengthValidator'),
    },
    {
        'NAME': ('django.contrib.auth.password_validation.'
                 'CommonPasswordValidator'),
    },
    {
        'NAME': ('django.contrib.auth.password_validation.'
                 'NumericPasswordValidator'),
    },
]


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATICFILES_DIRS = [
    'stylesheets'
]


# AWS

AWS_ACCESS_KEY_ID = os.environ.get(
    'AWS_ACCESS_KEY_ID',
    keys.AWS_ACCESS_KEY_ID
)
AWS_SECRET_ACCESS_KEY = os.environ.get(
    'AWS_SECRET_ACCESS_KEY',
    keys.AWS_SECRET_ACCESS_KEY
)


# Storage

DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

AWS_STORAGE_BUCKET_NAME = 'researchhub-paper-dev1'
AWS_S3_REGION_NAME = 'us-west-2'


# Email

AWS_SES_REGION_NAME = 'us-west-2'
AWS_SES_REGION_ENDPOINT = 'email.us-west-2.amazonaws.com'

EMAIL_BACKEND = 'django_ses.SESBackend'
if TESTING:
    EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

EMAIL_WHITELIST = [
    'craig@quantfive.org',
    'val@quantfive.org',
]


# Sentry

SENTRY_ENVIRONMENT = 'production' if PRODUCTION else 'dev'

if PRODUCTION:
    AWS_STORAGE_BUCKET_NAME = 'researchhub-paper-prod'

    def before_send(event, hint):
        log_record = hint.get('log_record')
        if log_record and 'Invalid HTTP_HOST header' in log_record.message:
            return None
        return event

    sentry_sdk.init(
        dsn="https://eddb587c90ec4e59916d46bcc43f2957@sentry.io/1797024",
        before_send=before_send,
        integrations=[DjangoIntegration()],
        environment=SENTRY_ENVIRONMENT
    )

AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None


# Search
ELASTICSEARCH_DSL = {
    'default': {
        'hosts': 'http://localhost:9200',
    },
}

if PRODUCTION:
    ELASTICSEARCH_DSL = {
        'default': {
            'hosts': 'https://search-researchhub-es-dev-gk44gqpe2rvt4e4qmx4y6vl2qq.us-west-2.es.amazonaws.com',  # noqa: E501
        },
    }

if STAGING:
    ELASTICSEARCH_DSL = {
        'default': {
            'hosts': 'https://search-researchhub-es-dev-gk44gqpe2rvt4e4qmx4y6vl2qq.us-west-2.es.amazonaws.com',  # noqa: E501
        },
    }

ELASTICSEARCH_AUTO_REINDEX = not PRODUCTION and os.environ.get(
    'ELASTICSEARCH_AUTO_REINDEX',
    False
)

if PRODUCTION:
    ELASTICSEARCH_AUTO_REINDEX = True

if STAGING:
    ELASTICSEARCH_AUTO_REINDEX = True


# Web3
# https://web3py.readthedocs.io/en/stable/

WEB3_PROVIDER_URL = os.environ.get(
    'WEB3_PROVIDER_URL',
    keys.INFURA_RINKEBY_ENDPOINT
)

WEB3_INFURA_PROJECT_ID = os.environ.get(
    'WEB3_INFURA_PROJECT_ID',
    keys.INFURA_PROJECT_ID
)

WEB3_INFURA_API_SECRET = os.environ.get(
    'WEB3_INFURA_API_SECRET',
    keys.INFURA_PROJECT_SECRET
)

WEB3_KEYSTORE_FILE = os.environ.get(
    'WEB3_KEYSTORE_FILE',
    wallet.KEYSTORE_FILE
)

WEB3_KEYSTORE_PASSWORD = os.environ.get(
    'WEB3_KEYSTORE_PASSWORD',
    wallet.KEYSTORE_PASSWORD
)


# Redis
# redis://:password@hostname:port/db_number

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = os.environ.get('REDIS_PORT', '6379')


# Celery

CELERY_BROKER_URL = 'redis://{}:{}/0'.format(REDIS_HOST, REDIS_PORT)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
