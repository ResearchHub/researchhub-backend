"""
Run the key-insights LLM pass (TLDR + strengths/weaknesses).

For each review, the model receives the proposal body, funding-opportunity
(grant) context, the platform AI peer-review comment text for that review, and
assessed human community reviews on the proposal post.

Only proposal reviews whose main AI review has finished are eligible
(``ProposalReview.status`` is ``Status.COMPLETED``).

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

from ai_peer_review.models import ProposalKeyInsight, ProposalReview, Status
from ai_peer_review.services.auto_run_guards import should_skip_key_insights
from ai_peer_review.services.proposal_key_insights_service import (
    ProposalKeyInsightsService,
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
        "Run key insights (TLDR + pros/cons) for each selected proposal review that has "
        "finished the main AI review (processed reviews only). Each LLM call uses proposal "
        "text, optional grant/funding context, the AI review comment, and assessed human "
        "community reviews. By default, skips reviews whose key insight already succeeded; "
        "use --force to re-run the LLM."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--grant-ids",
            type=str,
            default="",
            help=(
                "Comma-separated grant primary keys; selects processed "
                "(main review finished) proposal reviews for these grants."
            ),
        )
        parser.add_argument(
            "--review-ids",
            type=str,
            default="",
            help=(
                "Comma-separated ProposalReview primary keys (each must have finished "
                "the main AI review)."
            ),
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
                "Re-run key insights even when the key-insight row already succeeded "
                "(e.g. after prompt changes)."
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

        processed_review_qs = ProposalReview.objects.filter(status=Status.COMPLETED)
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
            reviews_qs = processed_review_qs.filter(grant_id__in=grant_ids)
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
            reviews_qs = processed_review_qs.filter(id__in=review_ids)
        else:
            q = Q(grant__isnull=False)
            if created_after:
                q &= Q(grant__created_date__gte=_parse_date(created_after))
            if created_before:
                q &= Q(grant__created_date__lte=_parse_date_end(created_before))
            reviews_qs = processed_review_qs.filter(q)

        selected_reviews = list(
            reviews_qs.select_related(
                "unified_document", "grant", "key_insight"
            ).order_by("id")
        )
        total = len(selected_reviews)
        generated = 0
        skipped = 0
        failed = 0

        processed_reviews = set(
            ProposalKeyInsight.objects.filter(
                proposal_review_id__in=[r.id for r in selected_reviews],
                status=Status.COMPLETED,
            ).values_list("proposal_review_id", flat=True)
        )

        self.stdout.write(
            self.style.NOTICE(
                f"Key insights: {total} processed proposal review(s) selected "
                "(main AI review finished)."
            )
        )
        if force:
            self.stdout.write(
                self.style.NOTICE(
                    "--force: re-running key insights even when a prior run succeeded."
                )
            )

        for i, review in enumerate(selected_reviews, start=1):
            key_insight_was_already_done = review.id in processed_reviews
            label = f"review={review.id} grant={review.grant_id}"
            skip, reason = should_skip_key_insights(review, force=force)
            if skip:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(f"[{i}/{total}] {label} SKIP (guard: {reason})")
                )
                continue
            try:
                ki = ProposalKeyInsightsService().run(review.id, force=force)
            except Exception as e:
                failed += 1
                logger.exception(
                    "ProposalKeyInsightsService.run failed for review %s",
                    review.id,
                )
                self.stdout.write(self.style.ERROR(f"[{i}/{total}] {label} ERROR: {e}"))
                continue

            if ki.status == Status.FAILED:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"[{i}/{total}] {label} FAILED: {ki.error_message[:200]!r}"
                    )
                )
            elif (
                not force
                and key_insight_was_already_done
                and ki.status == Status.COMPLETED
            ):
                skipped += 1
                self.stdout.write(
                    f"[{i}/{total}] {label} SKIP (key insight already succeeded)"
                )
            elif ki.status == Status.COMPLETED:
                generated += 1
                self.stdout.write(
                    self.style.SUCCESS(f"[{i}/{total}] {label} key insight succeeded")
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
