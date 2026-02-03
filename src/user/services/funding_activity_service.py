from decimal import Decimal
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q

from purchase.models import Purchase, UsdFundraiseContribution
from purchase.related_models.fundraise_model import Fundraise
from reputation.models import Bounty, Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_comment.models import RhCommentModel
from user.management.commands.setup_bank_user import BANK_EMAIL
from user.models import User
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.related_models.user_model import FOUNDATION_EMAIL


def get_leaderboard_excluded_user_ids():
    """
    User IDs that must not appear in leaderboard results (when building
    the Leaderboard table or when querying by date range). Their
    FundingActivity is still stored; they are only excluded from
    leaderboard display. Used by leaderboard task and views.
    """
    return list(
        User.objects.filter(
            Q(is_active=False)
            | Q(is_suspended=True)
            | Q(probable_spammer=True)
            | Q(email__in=[BANK_EMAIL, FOUNDATION_EMAIL])
        ).values_list("id", flat=True)
    )


class FundingActivityService:
    """
    Service for querying funding-related data and creating FundingActivity
    records with idempotency.
    """

    # Content types cached for reuse
    _purchase_content_type = None
    _comment_content_type = None
    _escrow_recipients_content_type = None
    _distribution_content_type = None
    _paper_content_type = None
    _post_content_type = None

    @classmethod
    def _get_content_type(cls, model):
        return ContentType.objects.get_for_model(model)

    @classmethod
    def get_purchase_content_type(cls):
        if cls._purchase_content_type is None:
            cls._purchase_content_type = cls._get_content_type(Purchase)
        return cls._purchase_content_type

    @classmethod
    def get_comment_content_type(cls):
        if cls._comment_content_type is None:
            cls._comment_content_type = cls._get_content_type(RhCommentModel)
        return cls._comment_content_type

    @classmethod
    def get_escrow_recipients_content_type(cls):
        if cls._escrow_recipients_content_type is None:
            cls._escrow_recipients_content_type = cls._get_content_type(
                EscrowRecipients
            )
        return cls._escrow_recipients_content_type

    @classmethod
    def get_distribution_content_type(cls):
        if cls._distribution_content_type is None:
            cls._distribution_content_type = cls._get_content_type(Distribution)
        return cls._distribution_content_type

    # -------------------------------------------------------------------------
    # Query methods
    # -------------------------------------------------------------------------

    @classmethod
    def get_fundraise_payouts(cls, start_date=None, end_date=None):
        """
        Completed fundraises with contributions: Purchases that are
        FUNDRAISE_CONTRIBUTION, PAID, and whose fundraise's escrow is PAID.
        """
        ct_fundraise = cls._get_content_type(Fundraise)
        qs = Purchase.objects.filter(
            content_type=ct_fundraise,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            fundraise__escrow__status=Escrow.PAID,
            fundraise__escrow__isnull=False,
        ).select_related("user", "content_type")
        if start_date:
            qs = qs.filter(created_date__gte=start_date)
        if end_date:
            qs = qs.filter(created_date__lte=end_date)
        return qs

    @classmethod
    def get_bounty_payouts(cls, start_date=None, end_date=None):
        """
        EscrowRecipients where escrow is PAID, hold_type is BOUNTY,
        and bounty type is REVIEW.
        """
        qs = (
            EscrowRecipients.objects.filter(
                escrow__status=Escrow.PAID,
                escrow__hold_type=Escrow.BOUNTY,
                escrow__bounties__bounty_type=Bounty.Type.REVIEW,
            )
            .select_related("escrow", "user")
            .distinct()
        )
        if start_date:
            qs = qs.filter(created_date__gte=start_date)
        if end_date:
            qs = qs.filter(created_date__lte=end_date)
        return qs

    @classmethod
    def get_document_tips(cls, start_date=None, end_date=None):
        """
        Purchase BOOST on papers/posts (paid).
        """
        from paper.models import Paper
        from researchhub_document.related_models.researchhub_post_model import (
            ResearchhubPost,
        )

        ct_paper = cls._get_content_type(Paper)
        ct_post = cls._get_content_type(ResearchhubPost)
        qs = Purchase.objects.filter(
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
            content_type__in=[ct_paper, ct_post],
        ).select_related("user", "content_type")
        if start_date:
            qs = qs.filter(created_date__gte=start_date)
        if end_date:
            qs = qs.filter(created_date__lte=end_date)
        return qs

    @classmethod
    def get_review_tips(cls, start_date=None, end_date=None):
        """
        Distribution PURCHASE for review comments (proof_item is a Purchase
        on a PEER_REVIEW or COMMUNITY_REVIEW comment).
        """
        ct_purchase = cls.get_purchase_content_type()
        review_purchase_ids = Purchase.objects.filter(
            content_type=cls.get_comment_content_type(),
            paid_status=Purchase.PAID,
            rh_comments__comment_type__in=[PEER_REVIEW, COMMUNITY_REVIEW],
        ).values_list("id", flat=True)
        qs = Distribution.objects.filter(
            distribution_type="PURCHASE",
            proof_item_content_type=ct_purchase,
            proof_item_object_id__in=review_purchase_ids,
        ).select_related("giver", "recipient", "proof_item_content_type")
        if start_date:
            qs = qs.filter(created_date__gte=start_date)
        if end_date:
            qs = qs.filter(created_date__lte=end_date)
        return qs

    @classmethod
    def get_fees(cls, start_date=None, end_date=None):
        """
        Distribution records for BOUNTY_DAO_FEE, BOUNTY_RH_FEE, SUPPORT_RH_FEE.

        NOTE: There is no strong way to connect completed spending RSC on the
        platform (e.g. payout bounty, fundraise contribution, support/BOOST)
        with the fee Distribution records—fee. All fees are included here regardless of whether they are
        related to completed, expired, or pending transactions, until we have
        a way to link fees to the underlying transaction outcome.
        """
        qs = Distribution.objects.filter(
            distribution_type__in=[
                "BOUNTY_DAO_FEE",
                "BOUNTY_RH_FEE",
                "SUPPORT_RH_FEE",
            ]
        ).select_related("giver", "recipient")
        if start_date:
            qs = qs.filter(created_date__gte=start_date)
        if end_date:
            qs = qs.filter(created_date__lte=end_date)
        return qs

    # -------------------------------------------------------------------------
    # Create with idempotency
    # -------------------------------------------------------------------------

    @classmethod
    def create_funding_activity(
        cls,
        source_type: str,
        source_object,
    ) -> Optional[FundingActivity]:
        """
        Create FundingActivity and FundingActivityRecipient(s) for the given
        source. Idempotent: if a FundingActivity already exists for this
        (source_content_type, source_object_id), returns the existing one
        without creating duplicates.

        Args:
            source_type: One of FundingActivity.FUNDRAISE_PAYOUT,
                BOUNTY_PAYOUT, TIP_DOCUMENT, TIP_REVIEW, FEE.
            source_object: The source instance (Purchase, EscrowRecipients,
                or Distribution).

        Returns:
            The FundingActivity instance, or None if creation was skipped
            (e.g. missing funder/recipient).
        """
        content_type = cls._get_content_type(source_object)
        with transaction.atomic():
            existing = FundingActivity.objects.filter(
                source_content_type=content_type,
                source_object_id=source_object.pk,
            ).first()
            if existing:
                return existing

            if source_type == FundingActivity.FUNDRAISE_PAYOUT:
                return cls._create_fundraise_payout_activity(source_object)
            if source_type == FundingActivity.FUNDRAISE_PAYOUT_USD:
                return cls._create_fundraise_payout_usd_activity(source_object)
            if source_type == FundingActivity.BOUNTY_PAYOUT:
                return cls._create_bounty_payout_activity(source_object)
            if source_type == FundingActivity.TIP_DOCUMENT:
                return cls._create_tip_document_activity(source_object)
            if source_type == FundingActivity.TIP_REVIEW:
                return cls._create_tip_review_activity(source_object)
            if source_type == FundingActivity.FEE:
                return cls._create_fee_activity(source_object)
        return None

    @classmethod
    def _create_fundraise_payout_activity(cls, purchase) -> Optional[FundingActivity]:
        """One FundingActivity per Purchase (FUNDRAISE_CONTRIBUTION, paid)."""
        if purchase.purchase_type != Purchase.FUNDRAISE_CONTRIBUTION:
            return None
        if purchase.paid_status != Purchase.PAID:
            return None
        fundraise = (
            Fundraise.objects.filter(
                pk=purchase.object_id,
                escrow__status=Escrow.PAID,
            )
            .select_related("escrow", "unified_document")
            .first()
        )
        if not fundraise or not fundraise.escrow:
            return None
        try:
            recipient_user = fundraise.get_recipient()
        except Exception:
            return None
        amount = Decimal(str(purchase.amount))
        activity = FundingActivity.objects.create(
            funder_id=purchase.user_id,
            source_type=FundingActivity.FUNDRAISE_PAYOUT,
            total_amount=amount,
            unified_document_id=fundraise.unified_document_id,
            activity_date=purchase.created_date,
            source_content_type=cls._get_content_type(Purchase),
            source_object_id=purchase.pk,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=recipient_user,
            amount=amount,
        )
        return activity

    @classmethod
    def _create_fundraise_payout_usd_activity(
        cls, usd_contribution: UsdFundraiseContribution
    ) -> Optional[FundingActivity]:
        """One FundingActivity per UsdFundraiseContribution when fundraise is completed."""
        if usd_contribution.is_refunded:
            return None
        if usd_contribution.amount_rsc is None:
            return None
        fundraise = (
            Fundraise.objects.filter(
                pk=usd_contribution.fundraise_id,
                status=Fundraise.COMPLETED,
                escrow__status=Escrow.PAID,
            )
            .select_related("escrow", "unified_document")
            .first()
        )
        if not fundraise or not fundraise.escrow:
            return None
        try:
            recipient_user = fundraise.get_recipient()
        except Exception:
            return None
        amount = Decimal(str(usd_contribution.amount_rsc))
        activity = FundingActivity.objects.create(
            funder_id=usd_contribution.user_id,
            source_type=FundingActivity.FUNDRAISE_PAYOUT_USD,
            total_amount=amount,
            unified_document_id=fundraise.unified_document_id,
            activity_date=usd_contribution.created_date,
            source_content_type=cls._get_content_type(UsdFundraiseContribution),
            source_object_id=usd_contribution.pk,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=recipient_user,
            amount=amount,
        )
        return activity

    @classmethod
    def _create_bounty_payout_activity(
        cls, escrow_recipient: EscrowRecipients
    ) -> Optional[FundingActivity]:
        """One FundingActivity per EscrowRecipients (bounty payout)."""
        escrow = escrow_recipient.escrow
        if escrow.hold_type != Escrow.BOUNTY or escrow.status != Escrow.PAID:
            return None
        bounty = (
            escrow.bounties.filter(bounty_type=Bounty.Type.REVIEW)
            .select_related("unified_document")
            .first()
        )
        unified_doc_id = bounty.unified_document_id if bounty else None
        amount = escrow_recipient.amount
        activity = FundingActivity.objects.create(
            funder_id=escrow.created_by_id,
            source_type=FundingActivity.BOUNTY_PAYOUT,
            total_amount=amount,
            unified_document_id=unified_doc_id,
            activity_date=escrow_recipient.created_date,
            source_content_type=cls._get_content_type(EscrowRecipients),
            source_object_id=escrow_recipient.pk,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=escrow_recipient.user,
            amount=amount,
        )
        return activity

    @classmethod
    def _create_tip_document_activity(cls, purchase) -> Optional[FundingActivity]:
        """One FundingActivity per Purchase BOOST on paper/post."""
        if (
            purchase.purchase_type != Purchase.BOOST
            or purchase.paid_status != Purchase.PAID
        ):
            return None
        item = purchase.item
        if item is None:
            return None
        unified_doc = getattr(item, "unified_document", None)
        unified_doc_id = unified_doc.pk if unified_doc else None
        # Paper has uploaded_by; ResearchhubPost has created_by
        recipient_user = getattr(item, "uploaded_by", None) or getattr(
            item, "created_by", None
        )
        if recipient_user is None:
            return None
        amount = Decimal(str(purchase.amount))
        activity = FundingActivity.objects.create(
            funder_id=purchase.user_id,
            source_type=FundingActivity.TIP_DOCUMENT,
            total_amount=amount,
            unified_document_id=unified_doc_id,
            activity_date=purchase.created_date,
            source_content_type=cls._get_content_type(Purchase),
            source_object_id=purchase.pk,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=recipient_user,
            amount=amount,
        )
        return activity

    @classmethod
    def _create_tip_review_activity(cls, distribution) -> Optional[FundingActivity]:
        """One FundingActivity per Distribution PURCHASE (review tip)."""
        if distribution.distribution_type != "PURCHASE":
            return None
        if distribution.giver_id is None:
            return None
        proof_item = distribution.proof_item
        unified_doc_id = None
        if proof_item and hasattr(proof_item, "item"):
            comment = getattr(proof_item, "item", None)
            if comment and hasattr(comment, "thread"):
                thread = getattr(comment, "thread", None)
                if thread and hasattr(thread, "unified_document"):
                    ud = thread.unified_document
                    unified_doc_id = ud.pk if ud else None
        activity = FundingActivity.objects.create(
            funder_id=distribution.giver_id,
            source_type=FundingActivity.TIP_REVIEW,
            total_amount=distribution.amount,
            unified_document_id=unified_doc_id,
            activity_date=distribution.created_date,
            source_content_type=cls._get_content_type(Distribution),
            source_object_id=distribution.pk,
        )
        if distribution.recipient_id is not None:
            FundingActivityRecipient.objects.create(
                activity=activity,
                recipient_user_id=distribution.recipient_id,
                amount=distribution.amount,
            )
        return activity

    @classmethod
    def _create_fee_activity(cls, distribution) -> Optional[FundingActivity]:
        """One FundingActivity per fee Distribution (no recipient user)."""
        if distribution.distribution_type not in (
            "BOUNTY_DAO_FEE",
            "BOUNTY_RH_FEE",
            "SUPPORT_RH_FEE",
        ):
            return None
        if distribution.giver_id is None:
            return None
        activity = FundingActivity.objects.create(
            funder_id=distribution.giver_id,
            source_type=FundingActivity.FEE,
            total_amount=distribution.amount,
            unified_document_id=None,
            activity_date=distribution.created_date,
            source_content_type=cls._get_content_type(Distribution),
            source_object_id=distribution.pk,
        )
        return activity
