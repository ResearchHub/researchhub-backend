import decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.tasks import track_revenue_event
from purchase.models import Balance, Fundraise, Purchase
from purchase.related_models.constants import (
    MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
    MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
)
from purchase.related_models.constants.currency import RSC, USD
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.purchase_serializer import DynamicPurchaseSerializer
from purchase.utils import create_fundraise_with_escrow
from reputation.models import BountyFee, Escrow
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.constants.filters import HOT
from user.models import User
from user.permissions import IsModerator
from utils.sentry import log_error


class FundraiseViewSet(viewsets.ModelViewSet):
    queryset = Fundraise.objects.all()
    serializer_class = DynamicFundraiseSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == "create":
            return [IsModerator()]
        return super().get_permissions()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["pch_dfs_get_created_by"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        context["usr_dus_get_author_profile"] = {
            "_include_fields": (
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            )
        }
        context["pch_dfs_get_escrow"] = {
            "_include_fields": [
                "id",
                "amount_holding",
                "amount_paid",
                "status",
                "hold_type",
                "bounty_fee",
            ],
        }
        context["pch_dfs_get_contributors"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        return context

    def create(self, request, *args, **kwargs):
        data = request.data

        goal_amount = data.get("goal_amount", None)
        goal_currency = data.get("goal_currency", USD)
        unified_document_id = data.get("unified_document_id", None)
        # Currently we don't allow users to create their own fundraise.
        # Admins have to manually create them for now.
        # So we require a recipient_user_id, which gets set as the created_by user for the fundraise/escrow.
        # In the future, when users can create their own fundraises, we can remove this.
        recipient_user_id = data.get("recipient_user_id", None)
        post_id = data.get("post_id", None)

        # Validate body
        if goal_amount is None:
            return Response({"message": "goal_amount is required"}, status=400)
        if unified_document_id is None and post_id is None:
            return Response(
                {"message": "unified_document_id or post_id is required"}, status=400
            )
        if recipient_user_id is None:
            return Response({"message": "recipient_user_id is required"}, status=400)

        # Get unified_document object
        unified_document = None
        if unified_document_id:
            try:
                unified_document = ResearchhubUnifiedDocument.objects.get(
                    id=unified_document_id
                )
                if unified_document is None:
                    return Response(
                        {"message": "Unified document does not exist"}, status=400
                    )
            except ResearchhubUnifiedDocument.DoesNotExist:
                return Response(
                    {"message": "Unified document does not exist"}, status=400
                )
        elif post_id:
            try:
                post = ResearchhubPost.objects.get(id=post_id)
                if post is None:
                    return Response({"message": "Post does not exist"}, status=400)
                unified_document = post.unified_document
            except ResearchhubPost.DoesNotExist:
                return Response({"message": "Post does not exist"}, status=400)
        # Get recipient user object
        recipient_user = None
        if recipient_user_id:
            try:
                recipient_user = User.objects.get(id=recipient_user_id)
                if recipient_user is None:
                    return Response({"message": "User does not exist"}, status=400)
            except User.DoesNotExist:
                return Response({"message": "User does not exist"}, status=400)

        with transaction.atomic():
            # Create fundraise object
            # fundraise = Fundraise.objects.create(
            #     created_by=recipient_user,
            #     unified_document=unified_document,
            #     goal_amount=goal_amount,
            #     goal_currency=goal_currency,
            #     status=Fundraise.OPEN,
            # )
            # # Create escrow object
            # escrow = Escrow.objects.create(
            #     created_by=recipient_user,
            #     hold_type=Escrow.FUNDRAISE,
            #     content_type=ContentType.objects.get_for_model(Fundraise),
            #     object_id=fundraise.id,
            # )
            # fundraise.escrow = escrow
            # fundraise.save()
            fundraise, error_response = create_fundraise_with_escrow(
                user=recipient_user,
                unified_document=unified_document,
                goal_amount=goal_amount,
                goal_currency=goal_currency,
            )
            if error_response:
                return error_response

        context = self.get_serializer_context()
        serializer = self.get_serializer(fundraise, context=context)
        return Response(serializer.data)

    def _purchase_serializer_context(self):
        context = self.get_serializer_context()
        context["pch_dps_get_user"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        context["usr_dus_get_author_profile"] = {
            "_include_fields": (
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            )
        }
        return context

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def create_contribution(self, request, *args, **kwargs):
        data = request.data
        user = request.user

        fundraise_id = kwargs.get("pk", None)
        amount = data.get("amount", None)
        amount_currency = data.get("amount_currency", RSC)

        # Validate body
        if fundraise_id is None:
            return Response({"message": "fundraise_id is required"}, status=400)
        if amount is None:
            return Response({"message": "amount is required"}, status=400)
        if amount_currency != RSC:
            return Response({"message": "amount_currency must be RSC"}, status=400)
        try:
            amount = decimal.Decimal(amount)
        except Exception as e:
            log_error(e)
            return Response({"detail": "Invalid amount"}, status=400)

        # Check if amount is within limits
        if (
            amount < MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
            or amount > MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
        ):
            return Response(
                {
                    "message": f"Invalid amount. Minimum is {MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC}"
                },
                status=400,
            )

        # Get fundraise object
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
            if fundraise is None:
                return Response({"message": "Fundraise does not exist"}, status=400)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        # Check if fundraise is open
        if fundraise.status != Fundraise.OPEN:
            return Response({"message": "Fundraise is not open"}, status=400)
        # Check if fundraise is not already fulfilled
        raised_amount = fundraise.get_amount_raised(fundraise.goal_currency)
        if raised_amount >= fundraise.goal_amount:
            return Response({"message": "Fundraise is already fulfilled"}, status=400)
        # Check if fundraise is not expired
        if fundraise.is_expired():
            # TODO: We don't account for this case yet, because the initial MVP implementation
            # won't ever encounter this case. But this code is here just in case.
            # We should implement this in the future.
            return Response({"message": "Fundraise is expired"}, status=400)

        # Check if user created the fundraise
        if fundraise.created_by.id == user.id:
            return Response(
                {"message": "Cannot contribute to your own fundraise"}, status=400
            )

        # Calculate fees
        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(amount)

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            # Check if user has enough balance in their wallet
            user_balance = user.get_balance()
            if user_balance - (amount + fee) < 0:
                return Response({"message": "Insufficient balance"}, status=400)

            # Create purchase object
            # In the future, we may want to have the user POST /purchases and then call this EP with an ID.
            # Especially for on-chain purchases.
            purchase = Purchase.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Fundraise),
                object_id=fundraise.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status=Purchase.PAID,
                amount=amount,
            )

            # Deduct fees
            deduct_bounty_fees(user, fee, rh_fee, dao_fee, fee_object)

            # Create balance objects
            amount_str = amount.to_eng_string()
            fee_str = fee.to_eng_string()
            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(BountyFee),
                object_id=fee_object.id,
                amount=f"-{fee_str}",
            )
            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Purchase),
                object_id=purchase.id,
                amount=f"-{amount_str}",
            )

            # Track in Amplitude
            rh_fee_str = rh_fee.to_eng_string()
            track_revenue_event.apply_async(
                (
                    user.id,
                    "FUNDRAISE_CONTRIBUTION_FEE",
                    rh_fee_str,
                    None,
                    "OFF_CHAIN",
                ),
                priority=1,
            )

            # Update escrow object
            fundraise.escrow.amount_holding += amount
            fundraise.escrow.save()

        # If fundraise is fulfilled, update status to closed
        # and trigger escrow payout
        fundraise.refresh_from_db()
        raised_amount = fundraise.get_amount_raised(fundraise.goal_currency)
        if raised_amount >= fundraise.goal_amount:
            # the escrow payout functions creates + sends a notification
            did_payout = fundraise.payout_funds()
            if did_payout:
                fundraise.status = Fundraise.COMPLETED
                fundraise.save()
            else:
                return Response({"message": "Failed to payout funds"}, status=500)

        # return updated fundraise object
        context = self.get_serializer_context()
        serializer = self.get_serializer(fundraise, context=context)
        return Response(serializer.data)

    @action(
        methods=["GET"],
        detail=True,
        permission_classes=[AllowAny],
    )
    def contributions(self, request, *args, **kwargs):
        fundraise_id = kwargs.get("pk", None)

        # Get fundraise object
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
            if fundraise is None:
                return Response({"message": "Fundraise does not exist"}, status=400)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        # Get contributions for a fundraise
        purchases = fundraise.purchases.all()
        context = self._purchase_serializer_context()
        serializer = DynamicPurchaseSerializer(purchases, context=context, many=True)
        return Response(serializer.data)
