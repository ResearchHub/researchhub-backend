from __future__ import absolute_import, unicode_literals

import os

from celery import Celery
from celery.schedules import crontab

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
QUEUE_PAPER_METRICS = "paper_metrics"
QUEUE_X_METRICS = "x_metrics"
QUEUE_GITHUB_METRICS = "github_metrics"
QUEUE_BLUESKY_METRICS = "bluesky_metrics"
QUEUE_PAPER_MISC = "paper_misc"
QUEUE_PULL_PAPERS = "pull_papers"
QUEUE_LOGS = "logs"
QUEUE_PURCHASES = "purchases"
QUEUE_REPUTATION = "reputation"
QUEUE_CONTRIBUTIONS = "contributions"
QUEUE_AUTHOR_CLAIM = "author_claim"
QUEUE_PAPER_METADATA = "paper_metadata"
QUEUE_BOUNTIES = "bounties"
QUEUE_HUBS = "hubs"


# Scheduled tasks

app.conf.beat_schedule = {
    # Feed
    "feed-refresh-hot-scores": {
        "task": "feed.tasks.refresh_feed_hot_scores",
        "schedule": crontab(hour="*/8", minute=20),
        "options": {
            "priority": 1,
            "queue": QUEUE_CACHES,
        },
    },
    # Hub
    "hub_calculate-and-set-hub-counts": {
        "task": "hub.tasks.calculate_and_set_hub_counts",
        "schedule": crontab(minute=0, hour=0),
        "options": {
            "priority": 5,
            "queue": QUEUE_HUBS,
        },
    },
    # Purchase
    "purchase_update-purchases": {
        "task": "purchase.tasks.update_purchases",
        "schedule": crontab(minute="*/30"),
        "options": {
            "priority": 3,
            "queue": QUEUE_PURCHASES,
        },
    },
    "purchase_complete-eligible-fundraises": {
        "task": "purchase.tasks.complete_eligible_fundraises",
        "schedule": crontab(hour=12, minute=0),  # Run daily at 12:00 PM UTC
        "options": {
            "priority": 3,
            "queue": QUEUE_PURCHASES,
        },
    },
    # Reputation
    "reputation_check-deposits": {
        "task": "reputation.tasks.check_deposits",
        "schedule": crontab(minute="*/1"),
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
    "reputation_check-pending-withdrawals": {
        "task": "reputation.tasks.check_pending_withdrawals",
        "schedule": crontab(minute="*/5"),
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
    "reputation_check-hotwallet-balance": {
        "task": "reputation.tasks.check_hotwallet_balance",
        "schedule": crontab(minute="*/30"),
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
    "reputation_check-open-bounties": {
        "task": "reputation.tasks.check_open_bounties",
        "schedule": crontab(hour="0, 6, 12, 18", minute=0),
        "options": {
            "priority": 4,
            "queue": QUEUE_BOUNTIES,
        },
    },
    "reputation_recalculate-rep-all-users": {
        "task": "reputation.tasks.recalculate_rep_all_users",
        "schedule": crontab(hour=0, minute=0),
        "options": {
            "priority": 2,
            "queue": QUEUE_REPUTATION,
        },
    },
    "reputation_recalc-hot-score-for-open-bounties": {
        "task": "reputation.tasks.recalc_hot_score_for_open_bounties",
        "schedule": crontab(hour=12, minute=0),
        "options": {
            "priority": 4,
            "queue": QUEUE_BOUNTIES,
        },
    },
    # User
    "user_execute-editor-daily-payout-task": {
        "task": "user.tasks.tasks.execute_editor_daily_payout_task",
        "schedule": crontab(hour=23, minute=5),
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
    "user_execute_rsc_exchange_rate_record_tasks": {
        "task": "user.tasks.tasks.execute_rsc_exchange_rate_record_tasks",
        "schedule": crontab(hour="*", minute=0),  # every hour
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
    "leaderboard-refresh": {
        "task": "user.tasks.leaderboard_tasks.refresh_leaderboard_task",
        "schedule": crontab(hour="*/6", minute=0),
        "options": {"priority": 3, "queue": QUEUE_CACHES},
    },
    # Weekly RSC Burning
    "reputation_burn-revenue-rsc": {
        "task": "reputation.tasks.burn_revenue_rsc",
        "schedule": crontab(
            minute=0, hour=9, day_of_week="monday"
        ),  # Every Monday at 9 AM UTC
        "options": {
            "priority": 2,
            "queue": QUEUE_PURCHASES,
        },
    },
    # Paper ingestion tasks
    "paper-fetch-all": {
        "task": "paper.ingestion.pipeline.fetch_all_papers",
        "schedule": crontab(hour=1, minute=0),
        "options": {
            "priority": 1,
            "queue": QUEUE_PULL_PAPERS,
        },
    },
    "paper-openalex-enrichment": {
        "task": "paper.ingestion.tasks.enrich_papers_with_openalex",
        "kwargs": {"days": 30},
        "schedule": crontab(hour=4, minute=0),
        "options": {
            "priority": 2,
            "queue": QUEUE_PAPER_MISC,
        },
    },
    "paper-github-metrics-update": {
        "task": "paper.ingestion.tasks.update_recent_papers_with_github_metrics",
        "kwargs": {"days": 14},
        "schedule": crontab(hour=7, minute=0),
        "options": {
            "priority": 2,
            "queue": QUEUE_GITHUB_METRICS,
        },
    },
    "paper-bluesky-metrics-update": {
        "task": "paper.ingestion.tasks.update_recent_papers_with_bluesky_metrics",
        "kwargs": {"days": 14},
        "schedule": crontab(hour=10, minute=0),
        "options": {
            "priority": 2,
            "queue": QUEUE_BLUESKY_METRICS,
        },
    },
    "paper-x-metrics-update": {
        "task": "paper.ingestion.tasks.update_recent_papers_with_x_metrics",
        "kwargs": {"days": 14},
        "schedule": crontab(hour=13, minute=0),
        "options": {
            "priority": 2,
            "queue": QUEUE_X_METRICS,
        },
    },
}
