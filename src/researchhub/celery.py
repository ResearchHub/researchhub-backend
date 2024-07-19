from __future__ import absolute_import, unicode_literals

import os
import time

from celery import Celery, chord
from celery.schedules import crontab

from reputation.exceptions import ReputationDistributorError, WithdrawalError

# Set the default Django settings module for the 'celery' program.
# This must come before instantiating Celery apps.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "researchhub.settings")

app = Celery("researchhub")

# Namespace='CELERY' means all celery-related configuration keys
# should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Loads tasks in `tasks.py` from installed apps.
app.autodiscover_tasks()

# Queues
QUEUE_CACHES = "caches"
QUEUE_HOT_SCORE = "hot_score"
QUEUE_ELASTIC_SEARCH = "elastic_search"
QUEUE_EXTERNAL_REPORTING = "external_reporting"
QUEUE_NOTIFICATION = "notifications"
QUEUE_PAPER_MISC = "paper_misc"
QUEUE_CERMINE = "cermine"
QUEUE_PULL_PAPERS = "pull_papers"
QUEUE_LOGS = "logs"
QUEUE_PURCHASES = "purchases"
QUEUE_CONTRIBUTIONS = "contributions"
QUEUE_AUTHOR_CLAIM = "author_claim"
QUEUE_PAPER_METADATA = "paper_metadata"
QUEUE_BOUNTIES = "bounties"
QUEUE_HUBS = "hubs"


# Scheduled tasks


app.conf.beat_schedule = {
    "log-daily-uploads": {
        "task": "paper.tasks.log_daily_uploads",
        "schedule": crontab(minute=50, hour=23),
        "options": {
            "priority": 2,
            "queue": QUEUE_EXTERNAL_REPORTING,
        },
    },
}


app.conf.beat_schedule = {
    "pull-new-openalex-works": {
        "task": "paper.tasks.pull_new_openalex_works",
        "schedule": crontab(minute=0, hour=6),
        "options": {
            "priority": 3,
            "queue": QUEUE_PULL_PAPERS,
        },
    },
}

app.conf.beat_schedule = {
    "celery-update-hot-scores": {
        "task": "paper.tasks.celery_update_hot_scores",
        "schedule": crontab(minute=0, hour=0),
        "options": {
            "priority": 5,
            "queue": QUEUE_HOT_SCORE,
        },
    },
}


app.conf.beat_schedule = {
    "calculate-and-set-hub-counts": {
        "task": "hub.tasks.calculate_and_set_hub_counts",
        "schedule": crontab(minute=0, hour=0),
        "options": {
            "priority": 5,
            "queue": QUEUE_HUBS,
        },
    },
}


app.conf.beat_schedule = {
    "weekly-bounty-digest": {
        "task": "mailing_list.tasks.weekly_bounty_digest",
        "schedule": crontab(minute=0, hour=8, day_of_week="friday"),
        "options": {
            "priority": 9,
            "queue": QUEUE_NOTIFICATION,
        },
    },
}

app.conf.beat_schedule = {
    "execute-editor-daily-payout-task": {
        "task": "user.tasks.execute_editor_daily_payout_task",
        "schedule": crontab(hour=23, minute=5),
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
}

app.conf.beat_schedule = {
    "hourly-purchase-task": {
        "task": "user.tasks.hourly_purchase_task",
        "schedule": crontab(hour="*", minute=0),  # every hour
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
}

app.conf.beat_schedule = {
    "check-deposits": {
        "task": "reputation.tasks.check_deposits",
        "schedule": crontab(minute="*/5"),
        "options": {
            "priority": 3,
            "queue": QUEUE_PURCHASES,
        },
    },
}

app.conf.beat_schedule = {
    "check-deposits": {
        "task": "reputation.tasks.check_pending_withdrawals",
        "schedule": crontab(minute="*/5"),
        "options": {
            "priority": 4,
            "queue": QUEUE_PURCHASES,
        },
    },
}


app.conf.beat_schedule = {
    "update-purchases": {
        "task": "purchase.tasks.update_purchases",
        "schedule": crontab(minute="*/30"),
        "options": {
            "priority": 3,
            "queue": QUEUE_PURCHASES,
        },
    },
}

app.conf.beat_schedule = {
    "check-hotwallet-balance": {
        "task": "reputation.tasks.check_hotwallet_balance",
        "schedule": crontab(minute="*/30"),
        "options": {
            "priority": 4,
            "queue": QUEUE_PURCHASES,
        },
    },
}

app.conf.beat_schedule = {
    "check-open-bounties": {
        "task": "reputation.tasks.check_open_bounties",
        "schedule": crontab(hour="0, 6, 12, 18", minute=0),
        "options": {
            "priority": 4,
            "queue": QUEUE_BOUNTIES,
        },
    },
}


app.conf.beat_schedule = {
    "send-bounty-hub-notifications": {
        "task": "reputation.tasks.send_bounty_hub_notifications",
        "schedule": crontab(hour="0, 6, 12, 18", minute=0),
        "options": {
            "priority": 5,
            "queue": QUEUE_BOUNTIES,
        },
    },
}


app.conf.beat_schedule = {
    "recalc-hot-score-for-open-bounties": {
        "task": "reputation.tasks.recalc_hot_score_for_open_bounties",
        "schedule": crontab(hour=12, minute=0),
        "options": {
            "priority": 4,
            "queue": QUEUE_BOUNTIES,
        },
    },
}


# Celery Debug/Test Functions
@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request}")


@app.task(bind=True)
def test_1(self, error_debug=False):
    time.sleep(2)
    print("Test 1")

    if error_debug:
        retries = self.request.retries
        try:
            print(f"Error 1: {retries}")
            if retries == 0:
                raise ReputationDistributorError("", "")
            elif retries == 1:
                raise WithdrawalError("", "")
            print("Test 1 Good")
        except (ReputationDistributorError, WithdrawalError) as exc:
            raise self.retry(exc=exc, countdown=0)


@app.task(bind=True)
def test_2(self):
    time.sleep(2)
    print("Test 2")
    return 2


@app.task(bind=True)
def test_3(self):
    time.sleep(2)
    print("Test 3")
    return 3


@app.task(bind=True)
def test_4(self):
    time.sleep(1)
    print("Test 4")
    return 4


@app.task(bind=True)
def test_5(self, nums):
    return sum(nums)


@app.task(bind=True)
def test_6(self):
    ch = chord([test_2.s(), test_3.s(), test_4.s()])(test_5.s())
    return ch


def run_chord_test():
    ch = test_6()
    print(ch)
    return ch


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
