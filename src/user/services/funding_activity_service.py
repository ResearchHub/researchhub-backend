import logging
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, Sum

from purchase.models import Purchase
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
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

logger = logging.getLogger(__name__)


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


def get_funder_total_amount(user_id, start_date=None, end_date=None):
    """
    Sum of FundingActivity.total_amount for a user as funder.
    Matches funder leaderboard aggregation.
    """
    qs = FundingActivity.objects.filter(funder_id=user_id)
    if start_date is not None:
        qs = qs.filter(activity_date__gte=start_date)
    if end_date is not None:
        qs = qs.filter(activity_date__lte=end_date)
    return qs.aggregate(total=Sum("total_amount"))["total"] or 0


class FundingActivityService:
    """
    Service for querying funding-related data and creating FundingActivity
    records with idempotency.
    """

    @classmethod
    def _get_content_type(cls, model):
        return ContentType.objects.get_for_model(model)

    @classmethod
    def _should_record_funding_recipient(cls, recipient_user) -> bool:
        """Skip recipient rows for the Endaoment holding account (not a real earner)."""
        endaoment_id = settings.ENDAOMENT_ACCOUNT_ID
        if not endaoment_id:
            return True
        return recipient_user.id != int(endaoment_id)

    @classmethod
    def _get_historical_rsc_usd_rate(cls, at_datetime) -> float | None:
        """Return Coalesce(real_rate, rate) for the latest USD rate at or before at_datetime."""
        rate_record = (
            RscExchangeRate.objects.filter(
                created_date__lte=at_datetime,
                target_currency="USD",
            )
            .order_by("-created_date")
            .first()
        )
        if rate_record is None:
            return None
        return (
            rate_record.real_rate
            if rate_record.real_rate is not None
            else rate_record.rate
        )

    @classmethod
    def _resolve_rate_for_purchase(cls, purchase) -> float | None:
        """Prefer purchase.rsc_usd_rate, else historical rate at purchase.created_date."""
        if purchase.rsc_usd_rate is not None:
            return purchase.rsc_usd_rate
        return cls._get_historical_rsc_usd_rate(purchase.created_date)

    @classmethod
    def _rsc_to_usd_cents(cls, rsc_amount, rate) -> int:
        return round(float(rsc_amount) * rate * 100)

    @classmethod
    def _usd_cents_to_rsc(cls, usd_cents, rate) -> Decimal:
        return Decimal(str(usd_cents / 100 / rate))

    @classmethod
    def _populate_dual_amounts_on_recipients(
        cls, activity, recipients_data, rate
    ) -> None:
        """
        Set total_usd_cents / amount_usd_cents from native RSC amounts and rate.
        When rate is unavailable, USD cents remain 0.
        """
        if rate is None:
            activity.total_usd_cents = 0
            for recipient in recipients_data:
                recipient.amount_usd_cents = 0
            return

        activity.total_usd_cents = cls._rsc_to_usd_cents(activity.total_amount, rate)
        for recipient in recipients_data:
            recipient.amount_usd_cents = cls._rsc_to_usd_cents(recipient.amount, rate)

    @classmethod
    def _populate_usd_native_dual_amounts_on_recipients(
        cls, activity, recipients_data, usd_cents, rate
    ) -> None:
        """
        Set native USD and calculated RSC on activity and recipients.
        Native USD cents are always set; RSC amounts use rate when available.
        """
        activity.total_usd_cents = usd_cents
        for recipient in recipients_data:
            recipient.amount_usd_cents = usd_cents

        if rate is None:
            activity.total_amount = Decimal("0")
            for recipient in recipients_data:
                recipient.amount = Decimal("0")
            return

        calculated_rsc = cls._usd_cents_to_rsc(usd_cents, rate)
        activity.total_amount = calculated_rsc
        for recipient in recipients_data:
            recipient.amount = calculated_rsc

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
    def get_usd_fundraise_payouts(cls, start_date=None, end_date=None):
        """
        Non-refunded USD contributions whose fundraise escrow is PAID.
        """
        qs = UsdFundraiseContribution.objects.filter(
            is_refunded=False,
            fundraise__escrow__status=Escrow.PAID,
            fundraise__escrow__isnull=False,
        ).select_related("user", "fundraise", "fundraise__unified_document")
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
        ct_purchase = cls._get_content_type(Purchase)
        review_purchase_ids = Purchase.objects.filter(
            content_type=cls._get_content_type(RhCommentModel),
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
                USD_FUNDRAISE_PAYOUT, BOUNTY_PAYOUT, TIP_DOCUMENT, TIP_REVIEW,
                FEE.
            source_object: The source instance (Purchase, UsdFundraiseContribution,
                EscrowRecipients, or Distribution).

        Returns:
            The FundingActivity instance, or None if creation was skipped
            (e.g. missing funder/recipient, or fundraise.get_recipient() could
            not resolve a recipient). Skips are intentional for backfill tasks;
            fundraise recipient failures are logged at warning level.
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
            if source_type == FundingActivity.USD_FUNDRAISE_PAYOUT:
                return cls._create_usd_fundraise_payout_activity(source_object)
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
        """
        One FundingActivity per Purchase (FUNDRAISE_CONTRIBUTION, paid).

        Returns None when fundraise.get_recipient() fails (e.g. nonprofit-linked
        fundraise without ENDAOMENT_ACCOUNT_ID, or Endaoment user missing).
        Logs a warning and skips rather than raising.
        """
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
        except (ValueError, User.DoesNotExist):
            logger.warning(
                "Skipping fundraise payout FundingActivity for purchase_id=%s: "
                "get_recipient failed",
                purchase.pk,
                exc_info=True,
            )
            return None
        amount = Decimal(str(purchase.amount))
        activity = FundingActivity(
            funder_id=purchase.user_id,
            source_type=FundingActivity.FUNDRAISE_PAYOUT,
            total_amount=amount,
            unified_document_id=fundraise.unified_document_id,
            activity_date=purchase.created_date,
            source_content_type=cls._get_content_type(Purchase),
            source_object_id=purchase.pk,
        )
        recipients = []
        if cls._should_record_funding_recipient(recipient_user):
            recipients.append(
                FundingActivityRecipient(
                    recipient_user=recipient_user,
                    amount=amount,
                )
            )
        rate = cls._resolve_rate_for_purchase(purchase)
        cls._populate_dual_amounts_on_recipients(activity, recipients, rate)
        activity.save()
        for recipient in recipients:
            recipient.activity = activity
            recipient.save()
        return activity

    @classmethod
    def _create_usd_fundraise_payout_activity(
        cls, contribution: UsdFundraiseContribution
    ) -> Optional[FundingActivity]:
        """
        One FundingActivity per non-refunded UsdFundraiseContribution on PAID escrow.

        Returns None when fundraise.get_recipient() fails; logs a warning and
        skips, same as _create_fundraise_payout_activity.
        """
        if contribution.is_refunded:
            return None
        fundraise = (
            Fundraise.objects.filter(
                pk=contribution.fundraise_id,
                escrow__status=Escrow.PAID,
            )
            .select_related("escrow", "unified_document")
            .first()
        )
        if not fundraise or not fundraise.escrow:
            return None
        try:
            recipient_user = fundraise.get_recipient()
        except (ValueError, User.DoesNotExist):
            logger.warning(
                "Skipping USD fundraise payout FundingActivity for "
                "contribution_id=%s: get_recipient failed",
                contribution.pk,
                exc_info=True,
            )
            return None
        native_usd_cents = contribution.amount_cents
        activity = FundingActivity(
            funder_id=contribution.user_id,
            source_type=FundingActivity.USD_FUNDRAISE_PAYOUT,
            total_amount=Decimal("0"),
            unified_document_id=fundraise.unified_document_id,
            activity_date=contribution.created_date,
            source_content_type=cls._get_content_type(UsdFundraiseContribution),
            source_object_id=contribution.pk,
        )
        recipients = []
        if cls._should_record_funding_recipient(recipient_user):
            recipients.append(
                FundingActivityRecipient(
                    recipient_user=recipient_user,
                    amount=Decimal("0"),
                )
            )
        rate = cls._get_historical_rsc_usd_rate(contribution.created_date)
        cls._populate_usd_native_dual_amounts_on_recipients(
            activity, recipients, native_usd_cents, rate
        )
        activity.save()
        for recipient in recipients:
            recipient.activity = activity
            recipient.save()
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
        activity = FundingActivity(
            funder_id=escrow.created_by_id,
            source_type=FundingActivity.BOUNTY_PAYOUT,
            total_amount=amount,
            unified_document_id=unified_doc_id,
            activity_date=escrow_recipient.created_date,
            source_content_type=cls._get_content_type(EscrowRecipients),
            source_object_id=escrow_recipient.pk,
        )
        recipient = FundingActivityRecipient(
            recipient_user=escrow_recipient.user,
            amount=amount,
        )
        rate = cls._get_historical_rsc_usd_rate(escrow_recipient.created_date)
        cls._populate_dual_amounts_on_recipients(activity, [recipient], rate)
        activity.save()
        recipient.activity = activity
        recipient.save()
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
        activity = FundingActivity(
            funder_id=purchase.user_id,
            source_type=FundingActivity.TIP_DOCUMENT,
            total_amount=amount,
            unified_document_id=unified_doc_id,
            activity_date=purchase.created_date,
            source_content_type=cls._get_content_type(Purchase),
            source_object_id=purchase.pk,
        )
        recipient = FundingActivityRecipient(
            recipient_user=recipient_user,
            amount=amount,
        )
        rate = cls._resolve_rate_for_purchase(purchase)
        cls._populate_dual_amounts_on_recipients(activity, [recipient], rate)
        activity.save()
        recipient.activity = activity
        recipient.save()
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
        activity = FundingActivity(
            funder_id=distribution.giver_id,
            source_type=FundingActivity.TIP_REVIEW,
            total_amount=distribution.amount,
            unified_document_id=unified_doc_id,
            activity_date=distribution.created_date,
            source_content_type=cls._get_content_type(Distribution),
            source_object_id=distribution.pk,
        )
        recipients = []
        if distribution.recipient_id is not None:
            recipients.append(
                FundingActivityRecipient(
                    recipient_user_id=distribution.recipient_id,
                    amount=distribution.amount,
                )
            )
        rate = cls._get_historical_rsc_usd_rate(distribution.created_date)
        cls._populate_dual_amounts_on_recipients(activity, recipients, rate)
        activity.save()
        for recipient in recipients:
            recipient.activity = activity
            recipient.save()
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
        activity = FundingActivity(
            funder_id=distribution.giver_id,
            source_type=FundingActivity.FEE,
            total_amount=distribution.amount,
            unified_document_id=None,
            activity_date=distribution.created_date,
            source_content_type=cls._get_content_type(Distribution),
            source_object_id=distribution.pk,
        )
        rate = cls._get_historical_rsc_usd_rate(distribution.created_date)
        cls._populate_dual_amounts_on_recipients(activity, [], rate)
        activity.save()
        return activity
