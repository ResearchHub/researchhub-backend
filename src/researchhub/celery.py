from __future__ import absolute_import, unicode_literals

import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
# This must come before instantiating Celery apps.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'researchhub.settings')

app = Celery('researchhub')

# Namespace='CELERY' means all celery-related configuration keys
# should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Loads tasks in `tasks.py` from installed apps.
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request}')
