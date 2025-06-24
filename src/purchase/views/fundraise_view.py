import decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.tasks import track_revenue_event
from purchase.models import Balance, Fundraise, Purchase
from purchase.related_models.constants import (
    MAXIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
    MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
)
from purchase.related_models.constants.currency import RSC
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.purchase_serializer import DynamicPurchaseSerializer
from purchase.services.fundraise_service import FundraiseService
from referral.services.referral_bonus_service import ReferralBonusService
from reputation.models import BountyFee
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from user.models import User
from user.permissions import IsModerator
from user.related_models.follow_model import Follow
from utils.sentry import log_error


class FundraiseViewSet(viewsets.ModelViewSet):
    queryset = Fundraise.objects.all()
    serializer_class = DynamicFundraiseSerializer
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.fundraise_service = kwargs.pop("fundraise_service", FundraiseService())
        self.referral_bonus_service = kwargs.pop(
            "referral_bonus_service", ReferralBonusService()
        )
        return super().dispatch(request, *args, **kwargs)

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
        serializer = FundraiseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        with transaction.atomic():
            try:
                fundraise = self.fundraise_service.create_fundraise_with_escrow(
                    user=validated_data["recipient_user"],
                    unified_document=validated_data["unified_document"],
                    goal_amount=validated_data["goal_amount"],
                    goal_currency=validated_data["goal_currency"],
                )
            except serializers.ValidationError as e:
                return Response({"message": str(e)}, status=400)

        context = self.get_serializer_context()
        response_serializer = self.get_serializer(fundraise, context=context)
        return Response(response_serializer.data)

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
            # For fundraise contributions, we allow using locked balance
            user_balance = user.get_balance(include_locked=True)
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

            # Get user's available locked balance
            available_locked_balance = user.get_locked_balance()

            # Determine how to split the contribution amount
            locked_amount_used = min(available_locked_balance, amount)
            regular_amount_used = amount - locked_amount_used

            # Determine how to split the fees using remaining locked balance
            remaining_locked_balance = available_locked_balance - locked_amount_used
            locked_fee_used = min(remaining_locked_balance, fee)
            regular_fee_used = fee - locked_fee_used

            # Create balance records for the contribution amount
            if locked_amount_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(Purchase),
                    object_id=purchase.id,
                    amount=f"-{locked_amount_used.to_eng_string()}",
                    is_locked=True,
                    lock_type=Balance.LockType.REFERRAL_BONUS,
                )

            if regular_amount_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(Purchase),
                    object_id=purchase.id,
                    amount=f"-{regular_amount_used.to_eng_string()}",
                )

            # Create balance records for the fees
            if locked_fee_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(BountyFee),
                    object_id=fee_object.id,
                    amount=f"-{locked_fee_used.to_eng_string()}",
                    is_locked=True,
                    lock_type=Balance.LockType.REFERRAL_BONUS,
                )

            if regular_fee_used > 0:
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(BountyFee),
                    object_id=fee_object.id,
                    amount=f"-{regular_fee_used.to_eng_string()}",
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

            # Let the contributor follow the preregistration
            document = fundraise.unified_document.get_document()
            Follow.objects.get_or_create(
                user=user,
                object_id=document.id,
                content_type=ContentType.objects.get_for_model(document),
            )

            # Update escrow object
            fundraise.escrow.amount_holding += amount
            fundraise.escrow.save()

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

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def complete(self, request, *args, **kwargs):
        """
        Complete a fundraise and payout funds to the recipient.
        Only works if the fundraise is in OPEN status and has escrow funds.
        Only accessible to moderators.
        """
        fundraise_id = kwargs.get("pk", None)

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

        # Check if fundraise has funds to payout
        if not fundraise.escrow or fundraise.escrow.amount_holding <= 0:
            return Response({"message": "Fundraise has no funds to payout"}, status=400)

        # Payout the funds
        did_payout = fundraise.payout_funds()
        if did_payout:
            fundraise.status = Fundraise.COMPLETED
            fundraise.save()

            # Return updated fundraise object
            context = self.get_serializer_context()
            serializer = self.get_serializer(fundraise, context=context)
            return Response(serializer.data)
        else:
            return Response({"message": "Failed to payout funds"}, status=500)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsModerator],
    )
    def close(self, request, *args, **kwargs):
        """
        Close a fundraise and refund all contributions to their contributors.
        Only works if the fundraise is in OPEN status and has escrow funds.
        """
        fundraise_id = kwargs.get("pk", None)

        # Get fundraise object
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
            if fundraise is None:
                return Response({"message": "Fundraise does not exist"}, status=400)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        # Close the fundraise
        result = fundraise.close_fundraise()

        if result:
            # Return updated fundraise object
            context = self.get_serializer_context()
            serializer = self.get_serializer(fundraise, context=context)
            return Response(serializer.data)
        else:
            return Response(
                {
                    "message": "Failed to close fundraise. It may already be closed or have no funds to refund."
                },
                status=400,
            )
