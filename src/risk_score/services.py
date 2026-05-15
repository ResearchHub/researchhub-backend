from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from risk_score.constants import (
    DAILY_DOWNVOTE_SCORE_CAP,
    DAILY_UPVOTE_SCORE_CAP,
    DEFAULT_SCORE,
    RESTRICTED_THRESHOLD,
    SCORE_CEILING,
    SCORE_FLOOR,
    TRUSTED_THRESHOLD,
)
from risk_score.models import RiskScore, RiskScoreEvent

EventType = RiskScoreEvent.EventType


class RiskScoreService:
    """Service for managing user risk score calculations and event recording."""

    VOTE_CAPS = {
        EventType.CONTENT_UPVOTED: DAILY_UPVOTE_SCORE_CAP,
        EventType.CONTENT_DOWNVOTED: DAILY_DOWNVOTE_SCORE_CAP,
    }

    def get_score(self, user):
        risk_score, _ = RiskScore.objects.get_or_create(user=user)
        return risk_score.score

    def is_trusted(self, user):
        return self.get_score(user) <= TRUSTED_THRESHOLD

    def is_restricted(self, user):
        return self.get_score(user) >= RESTRICTED_THRESHOLD

    def record_event(self, user, event_type, *, delta=None, metadata=None, source=None):
        delta = self._resolve_delta(event_type, delta)

        with transaction.atomic():
            risk_score, _ = RiskScore.objects.select_for_update().get_or_create(
                user=user
            )

            if event_type in RiskScoreEvent.ONE_TIME_TYPES:
                if self._one_time_event_exists(user, event_type):
                    return None

            if event_type in RiskScoreEvent.VOTE_TYPES:
                if self._daily_vote_cap_reached(user, event_type):
                    return None

            new_score = self._clamp(risk_score.score + delta)

            event = RiskScoreEvent.objects.create(
                user=user,
                event_type=event_type,
                delta=delta,
                score_after=new_score,
                metadata=metadata or {},
                **self._source_fields(source),
            )

            risk_score.score = new_score
            risk_score.save(update_fields=["score"])

        return event

    def recalculate_from_ledger(self, user):
        total_delta = (
            RiskScoreEvent.objects.filter(user=user).aggregate(total=Sum("delta"))[
                "total"
            ]
            or 0
        )
        new_score = self._clamp(DEFAULT_SCORE + total_delta)

        risk_score, _ = RiskScore.objects.get_or_create(user=user)
        risk_score.score = new_score
        risk_score.save(update_fields=["score"])

        return new_score

    def _resolve_delta(self, event_type, provided_delta):
        if provided_delta is not None:
            return provided_delta

        default_delta = RiskScoreEvent.DELTAS.get(event_type)
        if default_delta is None:
            raise ValueError(f"Delta is required for event type '{event_type}'")

        return default_delta

    def _clamp(self, score):
        return max(SCORE_FLOOR, min(SCORE_CEILING, score))

    def _one_time_event_exists(self, user, event_type):
        return RiskScoreEvent.objects.filter(
            user=user, event_type=event_type
        ).exists()

    def _daily_vote_cap_reached(self, user, event_type):
        today = timezone.now().date()
        count = RiskScoreEvent.objects.filter(
            user=user,
            event_type=event_type,
            created_date__date=today,
        ).count()
        return count >= self.VOTE_CAPS[event_type]

    def _source_fields(self, source):
        if source is None:
            return {}
        return {
            "source_content_type": ContentType.objects.get_for_model(source),
            "source_object_id": source.pk,
        }
