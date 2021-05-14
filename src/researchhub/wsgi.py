"""
WSGI config for researchhub project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""
import newrelic.agent
import os

from django.core.wsgi import get_wsgi_application

CELERY_WORKER = os.environ.get('CELERY_WORKER', False)
APP_ENV = os.environ.get('APP_ENV') or 'development'

if not CELERY_WORKER and 'development' not in APP_ENV:
    newrelic.agent.initialize('./newrelic.ini', APP_ENV)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'researchhub.settings')

application = get_wsgi_application()
