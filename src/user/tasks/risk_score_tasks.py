from datetime import timedelta

from django.utils import timezone

from researchhub.celery import app
from user.related_models.risk_score_model import RiskScoreEvent
from user.services.risk_score_service import RiskScoreService

EventType = RiskScoreEvent.EventType


@app.task
def apply_account_age_bonus_task():
    """Grant ACCOUNT_AGE_BONUS to active users with accounts older than 90 days."""
    from user.models import User

    service = RiskScoreService()
    threshold = timezone.now() - timedelta(days=90)

    users = User.objects.filter(
        is_active=True,
        date_joined__lt=threshold,
    ).iterator()

    for user in users:
        service.record_event(user, EventType.ACCOUNT_AGE_BONUS)
