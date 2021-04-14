from __future__ import absolute_import, unicode_literals

import os
import time
from celery import Celery
from reputation.exceptions import ReputationDistributorError, WithdrawalError

# Set the default Django settings module for the 'celery' program.
# This must come before instantiating Celery apps.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'researchhub.settings')

app = Celery('researchhub')

# Namespace='CELERY' means all celery-related configuration keys
# should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Loads tasks in `tasks.py` from installed apps.
app.autodiscover_tasks()


# Celery Debug/Test Functions
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request}')


@app.task(bind=True)
def test_1(self, error_debug=False):
    time.sleep(2)
    print('Test 1')

    if error_debug:
        retries = self.request.retries
        try:
            print(f'Error 1: {retries}')
            if retries == 0:
                raise ReputationDistributorError('', '')
            elif retries == 1:
                raise WithdrawalError('', '')
            print('Test 1 Good')
        except (ReputationDistributorError, WithdrawalError) as exc:
            raise self.retry(exc=exc, countdown=0)


@app.task(bind=True)
def test_2(self):
    time.sleep(2)
    print('Test 2')


@app.task(bind=True)
def test_3(self):
    time.sleep(2)
    print('Test 3')


@app.task(bind=True)
def test_4(self):
    time.sleep(2)
    print('Test 4')


# Test Results
"""
from researchhub.celery import test_1, test_2, test_3, test_4

test_4.apply_async(priority=5)
test_3.apply_async(priority=5)
test_2.apply_async(priority=1)
test_1.apply_async(priority=1)

4
2
1
3



test_1.apply_async(kwargs={'error_debug': True}, priority=1)
test_2.apply_async(priority=1)
test_3.apply_async(priority=1)
test_4.apply_async(priority=1)

1
2
3
4
1
1
"""
