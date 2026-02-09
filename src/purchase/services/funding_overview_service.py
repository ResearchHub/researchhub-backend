from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Count, IntegerField, When
from django.utils import timezone

from purchase.models import Fundraise, Grant, GrantApplication
from purchase.utils import get_funded_fundraise_ids, get_grant_fundraise_ids, sum_contributions
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from user.models import User

RECENT_UPDATES_DAYS = 30


class FundingOverviewService:
    """Service for calculating funding portfolio dashboard metrics for grant creators."""

    def get_funding_overview(self, user: User) -> dict:
        """Return funding overview metrics for a given user."""

        grant_fundraise_ids = get_grant_fundraise_ids(user)
        proposal_post_ids = self._get_proposal_post_ids(user)
        user_funded_ids = set(get_funded_fundraise_ids(user.id))
        funded_grant_proposals = list(set(grant_fundraise_ids) & user_funded_ids)

        return {
            "total_distributed_usd": sum_contributions(
                user_id=user.id, fundraise_ids=grant_fundraise_ids
            ),
            "active_grants": self._active_grants(user),
            "total_applicants": self._count_applicants(user),
            "matched_funding_usd": sum_contributions(
                fundraise_ids=funded_grant_proposals, exclude_user_id=user.id
            ),
            "recent_updates": self._update_count(proposal_post_ids, RECENT_UPDATES_DAYS),
            "proposals_funded": len(funded_grant_proposals),
        }

    def _get_grant_fundraise_ids(self, user: User) -> list[int]:
        """Get fundraise IDs for proposals connected to user's grants."""
        # Get prereg posts from applications to user's grants
        prereg_post_ids = GrantApplication.objects.filter(
            grant__unified_document__posts__created_by=user
        ).values_list("preregistration_post_id", flat=True)

        # Get fundraises for those prereg posts
        return list(
            Fundraise.objects.filter(
                unified_document__posts__id__in=prereg_post_ids
            ).values_list("id", flat=True).distinct()
        )

    def _count_applicants(self, user: User) -> dict:
        """Count total proposals attached to user's grants."""
        applications = GrantApplication.objects.filter(
            grant__unified_document__posts__created_by=user
        )
        result = applications.aggregate(
            total=Count("preregistration_post_id", distinct=True),
            active=Count(
                Case(
                    When(
                        preregistration_post__unified_document__fundraises__status=Fundraise.OPEN,
                        then="preregistration_post_id",
                    ),
                    output_field=IntegerField(),
                ),
                distinct=True,
            ),
        )
        return {
            "total": result["total"],
            "active": result["active"],
            "previous": result["total"] - result["active"],
        }

    def _get_proposal_post_ids(self, user: User) -> list[int]:
        """Get post IDs for proposals that applied to user's grants (for update tracking)."""
        return list(
            GrantApplication.objects.filter(
                grant__unified_document__posts__created_by=user
            ).values_list(
                "preregistration_post_id", flat=True
            ).distinct()
        )

    def _active_grants(self, user: User) -> dict:
        """Count active and total grants where the user created the post."""
        now = timezone.now()
        user_grants = Grant.objects.filter(unified_document__posts__created_by=user)
        result = user_grants.aggregate(
            total=Count("id"),
            active=Count(
                Case(
                    When(
                        status=Grant.OPEN,
                        end_date__isnull=True,
                        then=1,
                    ),
                    When(
                        status=Grant.OPEN,
                        end_date__gt=now,
                        then=1,
                    ),
                    output_field=IntegerField(),
                )
            ),
        )
        return {"active": result["active"], "total": result["total"]}

    def _update_count(self, post_ids: list[int], days: int) -> int:
        """Count author updates on the given posts within the time window."""
        if not post_ids:
            return 0
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        return RhCommentModel.objects.filter(
            comment_type=AUTHOR_UPDATE,
            thread__content_type=post_ct,
            thread__object_id__in=post_ids,
            created_date__gte=timezone.now() - timedelta(days=days),
        ).count()
