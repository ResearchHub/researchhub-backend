from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Model, Sum
from django.utils import timezone

from user.constants.risk_score_constants import (
    DEFAULT_SCORE,
    RESTRICTED_THRESHOLD,
    TRUSTED_THRESHOLD,
)
from user.related_models.risk_score_model import RiskScore, RiskScoreEvent
from user.related_models.user_model import User
from utils.models import ModeratedDocumentMixin

EventType = RiskScoreEvent.EventType


class RiskScoreService:
    """Service for managing user risk score calculations and event recording."""

    def get_score(self, user: User) -> int:
        try:
            return RiskScore.objects.get(user=user).score
        except RiskScore.DoesNotExist:
            return DEFAULT_SCORE

    def is_trusted(self, user: User) -> bool:
        return self.get_score(user) >= TRUSTED_THRESHOLD

    def is_restricted(self, user: User) -> bool:
        return self.get_score(user) <= RESTRICTED_THRESHOLD

    def initial_work_status(self, user: User) -> str:
        """Status a newly submitted work should get: trusted users auto-approve,
        everyone else enters the moderation queue as pending."""
        if self.is_trusted(user):
            return ModeratedDocumentMixin.APPROVED
        return ModeratedDocumentMixin.PENDING

    def record_event(
        self,
        user: User,
        event_type: EventType,
        *,
        delta: int | None = None,
        source: Model | None = None,
        action_date: datetime | None = None,
    ) -> RiskScoreEvent | None:
        delta = self._resolve_delta(event_type, delta)
        source_ct, source_id = self._resolve_source(source)
        action_date = action_date or timezone.now()

        with transaction.atomic():
            risk_score, _ = RiskScore.objects.select_for_update().get_or_create(
                user=user
            )

            if event_type in RiskScoreEvent.ONE_TIME_TYPES:
                if self._one_time_event_exists(user, event_type):
                    return None

            if source is not None and self._source_event_exists(
                user, event_type, source_ct, source_id
            ):
                return None

            event = RiskScoreEvent.objects.create(
                user=user,
                event_type=event_type,
                delta=delta,
                source_content_type=source_ct,
                source_content_id=source_id,
                action_date=action_date,
            )

            risk_score.score = self._compute_score(user)
            risk_score.save(update_fields=["score"])

        return event

    def _compute_score(self, user: User) -> int:
        """Derive score from the ledger. Single source of truth."""
        total_delta = (
            RiskScoreEvent.objects.filter(user=user).aggregate(total=Sum("delta"))[
                "total"
            ]
            or 0
        )
        return DEFAULT_SCORE + total_delta

    def _resolve_delta(self, event_type: EventType, provided_delta: int | None) -> int:
        if provided_delta is not None:
            return provided_delta

        default_delta = RiskScoreEvent.DELTAS.get(event_type)
        if default_delta is None:
            raise ValueError(f"Delta is required for event type '{event_type}'")

        return default_delta

    def _one_time_event_exists(self, user: User, event_type: EventType) -> bool:
        return RiskScoreEvent.objects.filter(user=user, event_type=event_type).exists()

    def _source_event_exists(
        self,
        user: User,
        event_type: EventType,
        source_ct: ContentType | None,
        source_id: int | None,
    ) -> bool:
        return RiskScoreEvent.objects.filter(
            user=user,
            event_type=event_type,
            source_content_type=source_ct,
            source_content_id=source_id,
        ).exists()

    def _resolve_source(
        self, source: Model | None
    ) -> tuple[ContentType | None, int | None]:
        if source is None:
            return None, None
        return ContentType.objects.get_for_model(source), source.pk
