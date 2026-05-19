"""
Backfill RiskScore records for existing users by retroactively applying
one-time profile signals and historical action events.

Idempotent: safe to run multiple times. One-time events use service-layer
idempotency. Historical events use source-based deduplication (each event
is tied to the source object that triggered it).
"""

from datetime import timedelta

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from research_ai.models import Expert
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import (
    ResearchhubPost,
)
from review.models.review_model import Review
from risk_score.models import RiskScoreEvent
from risk_score.services import RiskScoreService
from user.models import User
from user.related_models.user_verification_model import UserVerification

EventType = RiskScoreEvent.EventType

HISTORICAL_SOURCES = [
    (Grant, {"status": Grant.OPEN}, EventType.WORK_APPROVED),
    (Grant, {"status": Grant.DECLINED}, EventType.WORK_DECLINED),
    (RhCommentModel, {"is_removed": True}, EventType.CONTENT_CENSORED),
    (ResearchhubPost, {"unified_document__is_removed": True}, EventType.CONTENT_CENSORED),
    (BountySolution, {"status": BountySolution.Status.AWARDED}, EventType.BOUNTY_AWARDED),
    (Review, {"is_assessed": True}, EventType.PEER_REVIEW_ASSESSED),
]


class Command(BaseCommand):
    help = (
        "Backfill risk scores for active users by applying one-time profile "
        "signals and historical action events. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.service = RiskScoreService()
        self.events_recorded = 0

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no changes will be written."))

        self._backfill_one_time_signals(dry_run)
        self._backfill_historical_events(dry_run)

        self.stdout.write(self.style.SUCCESS(
            f"Done. Total events recorded: {self.events_recorded}"
        ))

    def _backfill_one_time_signals(self, dry_run):
        self.stdout.write("  Backfilling one-time profile signals...")
        lookups = self._build_one_time_bonus_lookups()

        users = User.objects.filter(is_active=True).order_by("pk")
        for user in users.iterator():
            for event_type in self._detect_one_time_signals(user, lookups):
                if not dry_run:
                    result = self.service.record_event(user, event_type)
                    if result is None:
                        continue
                self.events_recorded += 1

    def _backfill_historical_events(self, dry_run):
        self.stdout.write("  Backfilling historical events...")
        active_user_ids = set(
            User.objects.filter(is_active=True).values_list("pk", flat=True)
        )

        for model, filters, event_type in HISTORICAL_SOURCES:
            manager = getattr(model, "all_objects", model.objects)
            qs = manager.filter(
                created_by_id__in=active_user_ids, **filters
            ).select_related("created_by")
            for obj in qs:
                self._record_if_new(obj.created_by, event_type, obj, dry_run)

        self._backfill_foundation_tips(active_user_ids, dry_run)

    def _backfill_foundation_tips(self, active_user_ids, dry_run):
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
            for c in RhCommentModel.all_objects.filter(pk__in=comment_ids)
            .select_related("created_by")
        }

        for purchase in purchases:
            comment = comments_by_id.get(purchase.object_id)
            if comment is None:
                continue
            if comment.created_by_id not in active_user_ids:
                continue
            self._record_if_new(
                comment.created_by, EventType.PEER_REVIEW_TIPPED, purchase, dry_run
            )

    def _record_if_new(self, user, event_type, source, dry_run):
        ct = ContentType.objects.get_for_model(source)
        already_exists = RiskScoreEvent.objects.filter(
            user=user,
            event_type=event_type,
            source_content_type=ct,
            source_content_id=source.pk,
        ).exists()

        if already_exists:
            return

        if not dry_run:
            self.service.record_event(user, event_type, source=source)
        self.events_recorded += 1

    def _build_one_time_bonus_lookups(self):
        age_bonus_threshold = timezone.now() - timedelta(days=90)

        return {
            "expert_user_ids": set(
                Expert.objects.filter(
                    registered_user__isnull=False
                ).values_list("registered_user_id", flat=True)
            ),
            "google_user_ids": set(
                SocialAccount.objects.filter(
                    provider="google"
                ).values_list("user_id", flat=True)
            ),
            "orcid_accounts_with_edu": {
                sa.user_id
                for sa in SocialAccount.objects.filter(provider="orcid")
                if sa.extra_data.get("verified_edu_emails")
            },
            "persona_approved_user_ids": set(
                UserVerification.objects.filter(
                    status=UserVerification.Status.APPROVED
                ).values_list("user_id", flat=True)
            ),
            "age_bonus_threshold": age_bonus_threshold,
        }

    def _detect_one_time_signals(self, user, lookups):
        signals = []

        if user.pk in lookups["expert_user_ids"]:
            signals.append(EventType.EXPERT_FINDER_SIGNUP)

        if user.pk in lookups["google_user_ids"]:
            signals.append(EventType.GOOGLE_SIGNUP)

        if user.email and user.email.lower().endswith(".edu"):
            signals.append(EventType.EDU_EMAIL_SIGNUP)

        if user.pk in lookups["orcid_accounts_with_edu"]:
            signals.append(EventType.ORCID_VERIFIED_EDU)

        if user.pk in lookups["persona_approved_user_ids"]:
            signals.append(EventType.PERSONA_VERIFIED_WHITELISTED)

        if user.date_joined and user.date_joined < lookups["age_bonus_threshold"]:
            signals.append(EventType.ACCOUNT_AGE_BONUS)

        return signals
