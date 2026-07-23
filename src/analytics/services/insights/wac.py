from discussion.models import Vote
from purchase.models import Purchase, UsdFundraiseContribution
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.models import User, UserVerification


def get_contributor_metrics(period):
    """Count users who upvoted, commented, reviewed, proposed, or funded."""
    contributor_ids = set(
        Vote.objects.filter(
            vote_type=Vote.UPVOTE,
            updated_date__gte=period.start,
            updated_date__lt=period.end,
        ).values_list("created_by_id", flat=True)
    )
    contributor_ids.update(
        RhCommentModel.objects.filter(
            is_removed=False,
            created_date__gte=period.start,
            created_date__lt=period.end,
        ).values_list("created_by_id", flat=True)
    )
    contributor_ids.update(
        ResearchhubPost.objects.filter(
            document_type=PREREGISTRATION,
            unified_document__is_removed=False,
            created_date__gte=period.start,
            created_date__lt=period.end,
        ).values_list("created_by_id", flat=True)
    )
    contributor_ids.update(
        Purchase.objects.funding_contributions()
        .filter(
            paid_status=Purchase.PAID,
            created_date__gte=period.start,
            created_date__lt=period.end,
        )
        .values_list("user_id", flat=True)
    )
    contributor_ids.update(
        UsdFundraiseContribution.objects.not_refunded()
        .filter(
            status=UsdFundraiseContribution.Status.SUBMITTED,
            created_date__gte=period.start,
            created_date__lt=period.end,
        )
        .values_list("user_id", flat=True)
    )
    contributor_ids.discard(None)

    active_contributor_ids = set(
        User.objects.filter(
            id__in=contributor_ids,
            is_suspended=False,
            probable_spammer=False,
        ).values_list("id", flat=True)
    )
    verified_wac = UserVerification.objects.filter(
        user_id__in=active_contributor_ids,
        status=UserVerification.Status.APPROVED,
    ).count()

    return {
        "wac": {
            "count": len(active_contributor_ids),
            "definition": (
                "Distinct non-suspended, non-spam users who upvoted, commented "
                "or reviewed, published a proposal, or funded"
            ),
        },
        "verified_wac": {
            "count": verified_wac,
            "definition": "WAC users whose current verification status is APPROVED",
        },
    }
