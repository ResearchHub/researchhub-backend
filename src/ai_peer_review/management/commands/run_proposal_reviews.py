"""
Run AI proposal reviews synchronously for grant applications and refresh executive comparison.

Usage:
    python manage.py run_proposal_reviews --grant-ids 1,2,3
    python manage.py run_proposal_reviews --created-after 2024-01-01
    python manage.py run_proposal_reviews --created-before 2025-12-31 --created-after 2025-01-01
    python manage.py run_proposal_reviews --grant-ids 1 --force  # re-run completed proposal reviews too
"""

from __future__ import annotations

import logging
from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch, Q
from django.utils import timezone

from ai_peer_review.models import ProposalReview, Status
from ai_peer_review.services.auto_run_guards import AutoRunGuardsService
from ai_peer_review.services.proposal_review_service import (
    reset_proposal_review_for_rerun,
    run_proposal_review,
)
from ai_peer_review.services.rfp_summary_service import run_executive_comparison
from purchase.models import Grant, GrantApplication
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

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
        "Run AI proposal reviews for each preregistration linked to grants, "
        "then refresh executive comparison (no RFP brief). "
        "By default, already-completed reviews are skipped; use --force to re-run them."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--grant-ids",
            type=str,
            default="",
            help="Comma-separated grant primary keys (no open/deadline filter).",
        )
        parser.add_argument(
            "--created-after",
            type=str,
            default="",
            help="Include grants with created_date on or after this day (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--created-before",
            type=str,
            default="",
            help="Include grants with created_date on or before this day (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Re-run proposal reviews that are already COMPLETED (e.g. after prompt changes). "
                "Without this, only pending/failed reviews are executed; executive comparison "
                "still runs for each grant."
            ),
        )

    def handle(self, *args, **options):
        grant_ids_raw: str = (options["grant_ids"] or "").strip()
        created_after: str = (options["created_after"] or "").strip()
        created_before: str = (options["created_before"] or "").strip()
        force: bool = bool(options["force"])

        has_ids = bool(grant_ids_raw)
        has_dates = bool(created_after or created_before)
        if has_ids == has_dates:
            raise CommandError(
                "Provide exactly one mode: either --grant-ids or at least one of "
                "--created-after / --created-before."
            )

        if has_ids:
            id_strings = [x.strip() for x in grant_ids_raw.split(",") if x.strip()]
            if not id_strings:
                raise CommandError("--grant-ids must list at least one id.")
            try:
                grant_ids = [int(x) for x in id_strings]
            except ValueError as e:
                raise CommandError(
                    "--grant-ids must be comma-separated integers."
                ) from e
            grants_qs = (
                Grant.objects.filter(id__in=grant_ids)
                .select_related("unified_document", "created_by")
                .prefetch_related(
                    Prefetch(
                        "applications",
                        queryset=GrantApplication.objects.select_related(
                            "preregistration_post__unified_document"
                        ),
                    ),
                    "proposal_reviews",
                )
                .order_by("id")
            )
        else:
            q = Q(status=Grant.OPEN) & (
                Q(end_date__isnull=True) | Q(end_date__gt=timezone.now())
            )
            if created_after:
                q &= Q(created_date__gte=_parse_date(created_after))
            if created_before:
                q &= Q(created_date__lte=_parse_date_end(created_before))
            grants_qs = (
                Grant.objects.filter(q)
                .select_related("unified_document", "created_by")
                .prefetch_related(
                    Prefetch(
                        "applications",
                        queryset=GrantApplication.objects.select_related(
                            "preregistration_post__unified_document"
                        ),
                    ),
                    "proposal_reviews",
                )
                .order_by("id")
            )

        grants = list(grants_qs)
        total_grants = len(grants)
        proposals_run = 0
        proposals_skipped = 0
        proposals_failed = 0
        exec_ok = 0

        self.stdout.write(self.style.NOTICE(f"Found {total_grants} grant(s)."))
        if force:
            self.stdout.write(
                self.style.NOTICE(
                    "--force: re-running completed proposal reviews where applicable."
                )
            )

        for gi, grant in enumerate(grants, start=1):
            apps = list(grant.applications.all())
            prereg_apps = [
                a
                for a in apps
                if a.preregistration_post_id
                and a.preregistration_post.unified_document.document_type
                == PREREGISTRATION
            ]
            label = (
                grant.short_title or grant.organization or ""
            ).strip() or "(no title)"
            self.stdout.write(
                self.style.NOTICE(
                    f"Processing [{gi}/{total_grants}] grant={grant.id} "
                    f'"{label}" ({len(prereg_apps)} proposal(s))'
                )
            )

            for pj, app in enumerate(prereg_apps, start=1):
                ud = app.preregistration_post.unified_document
                try:
                    review, _created = ProposalReview.objects.get_or_create(
                        unified_document=ud,
                        grant=grant,
                        defaults={
                            "status": Status.PENDING,
                        },
                    )

                    if review.status == Status.COMPLETED and not force:
                        self.stdout.write(
                            f"  [{pj}/{len(prereg_apps)}] unified_document={ud.id} "
                            f"SKIP (already completed, review_id={review.id})"
                        )
                        proposals_skipped += 1
                        continue

                    skip, reason = AutoRunGuardsService.should_skip_proposal_review(
                        review, force=force
                    )
                    if skip:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [{pj}/{len(prereg_apps)}] unified_document={ud.id} "
                                f"SKIP (guard: {reason}, review_id={review.id})"
                            )
                        )
                        proposals_skipped += 1
                        continue

                    reset_proposal_review_for_rerun(review)
                    review.refresh_from_db()

                    self.stdout.write(
                        f"  [{pj}/{len(prereg_apps)}] unified_document={ud.id} "
                        f"running review_id={review.id} ..."
                    )
                    run_proposal_review(review.id)
                    review.refresh_from_db()
                    if review.status == Status.COMPLETED:
                        proposals_run += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [{pj}/{len(prereg_apps)}] unified_document={ud.id} "
                                f"{review.status} rating={review.overall_rating} "
                                f"numeric={review.overall_score_numeric}"
                            )
                        )
                    else:
                        proposals_failed += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"  [{pj}/{len(prereg_apps)}] unified_document={ud.id} "
                                f"{review.status}: {review.error_message[:200]!r}"
                            )
                        )
                except Exception as e:
                    proposals_failed += 1
                    logger.exception(
                        "run_proposal_reviews failed grant=%s ud=%s",
                        grant.id,
                        ud.id,
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [{pj}/{len(prereg_apps)}] unified_document={ud.id} ERROR: {e}"
                        )
                    )

            try:
                run_executive_comparison(grant.id, None)
                exec_ok += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Executive comparison updated for grant={grant.id}"
                    )
                )
            except ValueError as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Executive comparison skipped for grant={grant.id}: {e}"
                    )
                )
            except Exception as e:
                logger.exception("Executive comparison failed grant=%s", grant.id)
                self.stdout.write(
                    self.style.ERROR(
                        f"  Executive comparison failed for grant={grant.id}: {e}"
                    )
                )

        self.stdout.write(
            self.style.NOTICE(
                "Done. "
                f"grants={total_grants} proposals_run={proposals_run} "
                f"skipped={proposals_skipped} failed={proposals_failed} "
                f"exec_summaries={exec_ok}"
            )
        )
