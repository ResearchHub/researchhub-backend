"""
Backfill RiskScore records for existing users by retroactively applying
one-time profile signals and historical action counts.

Idempotent: safe to run multiple times. One-time events are skipped if already
recorded (enforced by RiskScoreService). Historical action counts are
recomputed fresh on each run (old BACKFILL events are replaced).
"""

from collections import defaultdict
from datetime import timedelta

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from discussion.models import Vote
from purchase.related_models.grant_model import Grant
from reputation.related_models.bounty import BountySolution
from research_ai.models import Expert
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models.review_model import Review
from risk_score.models import RiskScoreEvent
from risk_score.services import RiskScoreService
from user.models import User
from user.related_models.user_verification_model import UserVerification

EventType = RiskScoreEvent.EventType
DELTAS = RiskScoreEvent.DELTAS


class Command(BaseCommand):
    help = (
        "Backfill risk scores for active users by applying one-time profile "
        "signals and historical action counts. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing.",
        )
        parser.add_argument(
            "--log-freq",
            type=int,
            default=500,
            help="Log progress every N users (default: 500).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        log_freq = options["log_freq"]
        service = RiskScoreService()

        users = User.objects.filter(is_active=True).order_by("pk")
        total = users.count()
        self.stdout.write(f"Processing {total} active users.")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no changes will be written."))

        one_time_lookups = self._build_one_time_lookups()
        historical_lookups = self._build_historical_lookups()

        signal_stats = defaultdict(int)
        backfill_count = 0

        for i, user in enumerate(users.iterator(), start=1):
            # One-time signals (service idempotency prevents duplicates)
            signals = self._detect_one_time_signals(user, one_time_lookups)
            if not dry_run:
                for event_type in signals:
                    result = service.record_event(user, event_type)
                    if result is not None:
                        signal_stats[event_type] += 1
            else:
                for event_type in signals:
                    signal_stats[event_type] += 1

            # Historical action aggregate (recomputed each run)
            historical_delta = self._compute_historical_delta(
                user.pk, historical_lookups
            )
            if historical_delta != 0:
                if not dry_run:
                    RiskScoreEvent.objects.filter(
                        user=user, event_type=EventType.BACKFILL
                    ).delete()
                    service.record_event(
                        user, EventType.BACKFILL, delta=historical_delta
                    )
                backfill_count += 1

            # Recalculate to ensure consistency
            if not dry_run:
                service.recalculate_from_ledger(user)

            if i % log_freq == 0:
                self.stdout.write(f"  Progress: {i}/{total}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. One-time signals applied: {dict(signal_stats)}. "
            f"Users with historical backfill: {backfill_count}."
        ))

    def _build_one_time_lookups(self):
        self.stdout.write("  Building one-time signal lookups...")
        age_threshold = timezone.now() - timedelta(days=90)

        expert_user_ids = set(
            Expert.objects.filter(
                registered_user__isnull=False
            ).values_list("registered_user_id", flat=True)
        )

        google_user_ids = set(
            SocialAccount.objects.filter(
                provider="google"
            ).values_list("user_id", flat=True)
        )

        orcid_accounts_with_edu = {
            sa.user_id
            for sa in SocialAccount.objects.filter(provider="orcid")
            if sa.extra_data.get("verified_edu_emails")
        }

        persona_approved_user_ids = set(
            UserVerification.objects.filter(
                status=UserVerification.Status.APPROVED
            ).values_list("user_id", flat=True)
        )

        return {
            "expert_user_ids": expert_user_ids,
            "google_user_ids": google_user_ids,
            "orcid_accounts_with_edu": orcid_accounts_with_edu,
            "persona_approved_user_ids": persona_approved_user_ids,
            "age_threshold": age_threshold,
        }

    def _build_historical_lookups(self):
        self.stdout.write("  Building historical action lookups...")

        # Grants approved/declined per user
        grant_counts = {}
        for row in Grant.objects.values("created_by_id").annotate(
            approved=Count("id", filter=Q(status=Grant.OPEN)),
            declined=Count("id", filter=Q(status=Grant.DECLINED)),
        ):
            grant_counts[row["created_by_id"]] = (row["approved"], row["declined"])

        # Bounties awarded per user (solution creator)
        bounty_counts = dict(
            BountySolution.objects.filter(
                status=BountySolution.Status.AWARDED
            ).values_list("created_by_id").annotate(
                count=Count("id")
            ).values_list("created_by_id", "count")
        )

        # Reviews assessed per user
        review_counts = dict(
            Review.objects.filter(
                is_assessed=True
            ).values_list("created_by_id").annotate(
                count=Count("id")
            ).values_list("created_by_id", "count")
        )

        # Censored comments per user
        censored_comment_counts = dict(
            RhCommentModel.objects.filter(
                is_removed=True
            ).values_list("created_by_id").annotate(
                count=Count("id")
            ).values_list("created_by_id", "count")
        )

        # Censored posts/documents per user
        censored_doc_counts = dict(
            ResearchhubUnifiedDocument.objects.filter(
                is_removed=True,
                posts__isnull=False,
            ).values_list("posts__created_by_id").annotate(
                count=Count("id")
            ).values_list("posts__created_by_id", "count")
        )

        # Votes received on user's comments
        self.stdout.write("  Computing vote counts (this may take a moment)...")
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        upvotes_by_user = defaultdict(int)
        downvotes_by_user = defaultdict(int)

        comment_authors = dict(
            RhCommentModel.objects.values_list("id", "created_by_id")
        )
        for comment_id, vote_type in (
            Vote.objects.filter(content_type=comment_ct)
            .values_list("object_id", "vote_type")
            .iterator()
        ):
            author_id = comment_authors.get(comment_id)
            if author_id:
                if vote_type == Vote.UPVOTE:
                    upvotes_by_user[author_id] += 1
                elif vote_type == Vote.DOWNVOTE:
                    downvotes_by_user[author_id] += 1

        return {
            "grant_counts": grant_counts,
            "bounty_counts": bounty_counts,
            "review_counts": review_counts,
            "censored_comment_counts": censored_comment_counts,
            "censored_doc_counts": censored_doc_counts,
            "upvotes_by_user": upvotes_by_user,
            "downvotes_by_user": downvotes_by_user,
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

        if user.date_joined and user.date_joined < lookups["age_threshold"]:
            signals.append(EventType.ACCOUNT_AGE_BONUS)

        return signals

    def _compute_historical_delta(self, user_id, lookups):
        approved, declined = lookups["grant_counts"].get(user_id, (0, 0))
        bounties = lookups["bounty_counts"].get(user_id, 0)
        reviews = lookups["review_counts"].get(user_id, 0)
        censored_comments = lookups["censored_comment_counts"].get(user_id, 0)
        censored_docs = lookups["censored_doc_counts"].get(user_id, 0)
        upvotes = lookups["upvotes_by_user"].get(user_id, 0)
        downvotes = lookups["downvotes_by_user"].get(user_id, 0)

        delta = (
            approved * DELTAS[EventType.WORK_APPROVED]
            + declined * DELTAS[EventType.WORK_DECLINED]
            + bounties * DELTAS[EventType.BOUNTY_AWARDED]
            + reviews * DELTAS[EventType.PEER_REVIEW_ASSESSED]
            + (censored_comments + censored_docs) * DELTAS[EventType.CONTENT_CENSORED]
            + upvotes * DELTAS[EventType.CONTENT_UPVOTED]
            + downvotes * DELTAS[EventType.CONTENT_DOWNVOTED]
        )
        return delta
