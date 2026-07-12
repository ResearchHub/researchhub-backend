"""
Backfill RiskScore records for existing users by retroactively applying
one-time profile signals and historical action events.

Idempotent: safe to run multiple times. One-time events use service-layer
idempotency. Historical events use source-based deduplication (each event
is tied to the source object that triggered it).
"""

from datetime import datetime, timedelta

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import Min, Model
from django.utils import timezone

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from research_ai.models import Expert
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from review.models.review_model import Review
from user.models import User
from user.related_models.risk_score_model import RiskScoreEvent
from user.related_models.user_verification_model import UserVerification
from user.related_models.verdict_model import Verdict
from user.services.censorship import resolve_censorship
from user.services.risk_score_service import RiskScoreService

EventType = RiskScoreEvent.EventType

# Accounts older than this earn the age bonus; the bonus is dated to the day
# the account crossed the threshold.
ACCOUNT_AGE_BONUS_DAYS = 90


def _grant_decision_date(grant: Grant) -> datetime:
    return grant.updated_date


def _solution_award_date(solution: BountySolution) -> datetime:
    return solution.updated_date


def _review_assessment_date(review: Review) -> datetime:
    return review.updated_date


HISTORICAL_SOURCES = [
    (Grant, {"status": Grant.OPEN}, EventType.WORK_APPROVED, _grant_decision_date),
    (Grant, {"status": Grant.DECLINED}, EventType.WORK_DECLINED, _grant_decision_date),
    (
        BountySolution,
        {"status": BountySolution.Status.AWARDED},
        EventType.BOUNTY_AWARDED,
        _solution_award_date,
    ),
    (
        Review,
        {"is_assessed": True},
        EventType.PEER_REVIEW_ASSESSED,
        _review_assessment_date,
    ),
]


class Command(BaseCommand):
    help = (
        "Backfill risk scores for active users by applying one-time profile "
        "signals and historical action events. Idempotent."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]
        self.service = RiskScoreService()
        self.events_recorded = 0

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN: no changes will be written.")
            )

        self._backfill_one_time_signals(dry_run)
        self._backfill_historical_events(dry_run)

        self.stdout.write(
            self.style.SUCCESS(f"Done. Total events recorded: {self.events_recorded}")
        )

    def _backfill_one_time_signals(self, dry_run: bool) -> None:
        self.stdout.write("  Backfilling one-time profile signals...")
        lookups = self._build_one_time_signal_lookups()

        users = User.objects.filter(is_active=True).order_by("pk")
        for user in users.iterator():
            for event_type, occurred_at in self._detect_one_time_signals(user, lookups):
                self._record(user, event_type, dry_run, occurred_at=occurred_at)

    def _backfill_historical_events(self, dry_run: bool) -> None:
        self.stdout.write("  Backfilling historical events...")
        active_user_ids = set(
            User.objects.filter(is_active=True).values_list("pk", flat=True)
        )

        for model, filters, event_type, occurred_at in HISTORICAL_SOURCES:
            manager = getattr(model, "all_objects", model.objects)
            qs = manager.filter(
                created_by_id__in=active_user_ids, **filters
            ).select_related("created_by")
            for obj in qs:
                self._record(
                    obj.created_by,
                    event_type,
                    dry_run,
                    source=obj,
                    occurred_at=occurred_at(obj),
                )

        self._backfill_censorship_verdicts(active_user_ids, dry_run)
        self._backfill_foundation_tips(active_user_ids, dry_run)

    def _backfill_censorship_verdicts(
        self, active_user_ids: set[int], dry_run: bool
    ) -> None:
        """Backfill CONTENT_CENSORED for content a moderator removed via verdict."""
        verdicts = Verdict.objects.filter(is_content_removed=True).select_related(
            "flag__content_type"
        )
        for verdict in verdicts.iterator():
            author, source = resolve_censorship(verdict)
            if source is None or author is None or author.id not in active_user_ids:
                continue
            self._record(
                author,
                EventType.CONTENT_CENSORED,
                dry_run,
                source=source,
                occurred_at=verdict.created_date,
            )

    def _backfill_foundation_tips(
        self, active_user_ids: set[int], dry_run: bool
    ) -> None:
        """Backfill PEER_REVIEW_TIPPED for comments tipped by the foundation."""
        try:
            community = User.objects.get_community_account()
        except User.DoesNotExist:
            return

        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        purchases = list(
            Purchase.objects.filter(user=community, content_type=comment_ct)
        )

        comment_ids = {p.object_id for p in purchases}
        comments_by_id = {
            c.pk: c
            for c in RhCommentModel.all_objects.filter(
                pk__in=comment_ids
            ).select_related("created_by")
        }

        for purchase in purchases:
            comment = comments_by_id.get(purchase.object_id)
            if comment is None:
                continue
            if comment.created_by_id not in active_user_ids:
                continue
            self._record(
                comment.created_by,
                EventType.PEER_REVIEW_TIPPED,
                dry_run,
                source=purchase,
                occurred_at=purchase.created_date,
            )

    def _record(
        self,
        user: User,
        event_type: EventType,
        dry_run: bool,
        *,
        source: Model | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        """Record one event at its historical date, skipping duplicates."""
        if dry_run:
            self.events_recorded += 1
            return

        event = self.service.record_event(
            user, event_type, source=source, action_date=occurred_at
        )
        if event is None:
            return

        self.events_recorded += 1

    def _build_one_time_signal_lookups(self) -> dict:
        age_bonus_threshold = timezone.now() - timedelta(days=ACCOUNT_AGE_BONUS_DAYS)
        return {
            "expert_user_ids": set(
                Expert.objects.filter(registered_user__isnull=False).values_list(
                    "registered_user_id", flat=True
                )
            ),
            "google_dates": self._earliest_social_dates(provider="google"),
            "orcid_dates": self._earliest_orcid_edu_dates(),
            "persona_dates": dict(
                UserVerification.objects.filter(
                    status=UserVerification.Status.APPROVED
                ).values_list("user_id", "created_date")
            ),
            "age_bonus_threshold": age_bonus_threshold,
        }

    def _earliest_social_dates(self, *, provider: str) -> dict[int, datetime]:
        """Map user -> earliest link date for the given social provider."""
        return {
            row["user_id"]: row["joined"]
            for row in SocialAccount.objects.filter(provider=provider)
            .values("user_id")
            .annotate(joined=Min("date_joined"))
        }

    def _earliest_orcid_edu_dates(self) -> dict[int, datetime]:
        """Map user -> earliest ORCID link date, ORCID accounts with a
        verified .edu email only (filtered in Python; lives in extra_data)."""
        dates = {}
        for account in SocialAccount.objects.filter(provider="orcid"):
            if not account.extra_data.get("verified_edu_emails"):
                continue
            earliest = dates.get(account.user_id)
            if earliest is None or account.date_joined < earliest:
                dates[account.user_id] = account.date_joined
        return dates

    def _detect_one_time_signals(
        self, user: User, lookups: dict
    ) -> list[tuple[EventType, datetime | None]]:
        """Yield (event_type, occurred_at) for each one-time signal the user
        qualifies for, dated to when the user earned it."""
        signals = []

        if user.pk in lookups["expert_user_ids"]:
            signals.append((EventType.EXPERT_FINDER_SIGNUP, user.date_joined))

        google_date = lookups["google_dates"].get(user.pk)
        if google_date is not None:
            signals.append((EventType.GOOGLE_SIGNUP, google_date))

        has_edu_email = bool(user.email and user.email.lower().endswith(".edu"))
        orcid_edu_date = lookups["orcid_dates"].get(user.pk)
        if has_edu_email or orcid_edu_date is not None:
            edu_dates = [orcid_edu_date]
            if has_edu_email:
                edu_dates.append(user.date_joined)
            occurred_at = min((d for d in edu_dates if d is not None), default=None)
            signals.append((EventType.EDU_EMAIL, occurred_at))

        persona_date = lookups["persona_dates"].get(user.pk)
        if persona_date is not None:
            signals.append((EventType.PERSONA_VERIFIED_WHITELISTED, persona_date))

        if user.date_joined and user.date_joined < lookups["age_bonus_threshold"]:
            age_bonus_date = user.date_joined + timedelta(days=ACCOUNT_AGE_BONUS_DAYS)
            signals.append((EventType.ACCOUNT_AGE_BONUS, age_bonus_date))

        return signals
