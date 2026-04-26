"""
Run the key-insights LLM pass (TLDR + pros/cons) for completed proposal reviews.

Usage:
    python manage.py run_proposal_key_insights --grant-ids 1,2,3
    python manage.py run_proposal_key_insights --review-ids 10,20
    python manage.py run_proposal_key_insights --created-after 2024-01-01
    python manage.py run_proposal_key_insights --created-after 2025-01-01 --created-before 2025-12-31
    python manage.py run_proposal_key_insights --review-ids 42 --force
"""

import logging
from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from ai_peer_review.models import ProposalKeyInsight, ProposalReview, ReviewStatus
from ai_peer_review.services.proposal_key_insights_service import (
    run_proposal_key_insights,
)

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> datetime:
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise CommandError(f"Invalid date {s!r}; use YYYY-MM-DD.") from e
    return timezone.make_aware(datetime.combine(d, time.min))


def _parse_date_end(s: str) -> datetime:
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise CommandError(f"Invalid date {s!r}; use YYYY-MM-DD.") from e
    return timezone.make_aware(datetime.combine(d, time.max))


class Command(BaseCommand):
    help = (
        "Run key insights (TLDR + pros/cons) for each completed proposal review. "
        "By default, reviews that already have a completed key insight are skipped; "
        "use --force to re-run the LLM."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--grant-ids",
            type=str,
            default="",
            help=(
                "Comma-separated grant primary keys; selects completed "
                "reviews for these grants."
            ),
        )
        parser.add_argument(
            "--review-ids",
            type=str,
            default="",
            help=("Comma-separated ProposalReview primary keys (must be completed)."),
        )
        parser.add_argument(
            "--created-after",
            type=str,
            default="",
            help=(
                "Date mode: only reviews whose grant was created on or after "
                "this day (YYYY-MM-DD)."
            ),
        )
        parser.add_argument(
            "--created-before",
            type=str,
            default="",
            help=(
                "Date mode: only reviews whose grant was created on or before "
                "this day (YYYY-MM-DD)."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Re-run key insights that are already completed (e.g. after "
                "prompt changes)."
            ),
        )

    def handle(self, *args, **options):
        grant_ids_raw: str = (options["grant_ids"] or "").strip()
        review_ids_raw: str = (options["review_ids"] or "").strip()
        created_after: str = (options["created_after"] or "").strip()
        created_before: str = (options["created_before"] or "").strip()
        force: bool = bool(options["force"])

        has_grant = bool(grant_ids_raw)
        has_review = bool(review_ids_raw)
        has_dates = bool(created_after or created_before)
        modes = int(has_grant) + int(has_review) + int(has_dates)
        if modes != 1:
            raise CommandError(
                "Provide exactly one selection mode: --grant-ids, --review-ids, "
                "or at least one of --created-after / --created-before (grant "
                "created_date filter)."
            )

        base = ProposalReview.objects.filter(status=ReviewStatus.COMPLETED)
        if has_grant:
            id_strings = [x.strip() for x in grant_ids_raw.split(",") if x.strip()]
            if not id_strings:
                raise CommandError("--grant-ids must list at least one id.")
            try:
                grant_ids = [int(x) for x in id_strings]
            except ValueError as e:
                raise CommandError(
                    "--grant-ids must be comma-separated integers."
                ) from e
            reviews_qs = base.filter(grant_id__in=grant_ids)
        elif has_review:
            id_strings = [x.strip() for x in review_ids_raw.split(",") if x.strip()]
            if not id_strings:
                raise CommandError("--review-ids must list at least one id.")
            try:
                review_ids = [int(x) for x in id_strings]
            except ValueError as e:
                raise CommandError(
                    "--review-ids must be comma-separated integers."
                ) from e
            reviews_qs = base.filter(id__in=review_ids)
        else:
            q = Q(grant__isnull=False)
            if created_after:
                q &= Q(grant__created_date__gte=_parse_date(created_after))
            if created_before:
                q &= Q(grant__created_date__lte=_parse_date_end(created_before))
            reviews_qs = base.filter(q)

        reviews = list(
            reviews_qs.select_related("unified_document", "grant").order_by("id")
        )
        total = len(reviews)
        generated = 0
        skipped = 0
        failed = 0

        completed_before_ids = set(
            ProposalKeyInsight.objects.filter(
                proposal_review_id__in=[r.id for r in reviews],
                status=ReviewStatus.COMPLETED,
            ).values_list("proposal_review_id", flat=True)
        )

        self.stdout.write(
            self.style.NOTICE(
                f"Key insights: {total} completed proposal review(s) to process."
            )
        )
        if force:
            self.stdout.write(
                self.style.NOTICE(
                    "--force: re-running key insights that were already completed."
                )
            )

        for i, review in enumerate(reviews, start=1):
            before = review.id in completed_before_ids
            label = f"review={review.id} grant={review.grant_id}"
            try:
                ki = run_proposal_key_insights(review.id, force=force)
            except Exception as e:
                failed += 1
                logger.exception(
                    "run_proposal_key_insights failed for review %s",
                    review.id,
                )
                self.stdout.write(self.style.ERROR(f"[{i}/{total}] {label} ERROR: {e}"))
                continue

            if ki.status == ReviewStatus.FAILED:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"[{i}/{total}] {label} FAILED: {ki.error_message[:200]!r}"
                    )
                )
            elif not force and before and ki.status == ReviewStatus.COMPLETED:
                skipped += 1
                self.stdout.write(
                    f"[{i}/{total}] {label} SKIP (key insight already completed)"
                )
            elif ki.status == ReviewStatus.COMPLETED:
                generated += 1
                self.stdout.write(
                    self.style.SUCCESS(f"[{i}/{total}] {label} key insight COMPLETED")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"[{i}/{total}] {label} unexpected status {ki.status!r}"
                    )
                )

        self.stdout.write(
            self.style.NOTICE(
                "Done. "
                f"total={total} generated={generated} skipped={skipped} failed={failed}"
            )
        )
