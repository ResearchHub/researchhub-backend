from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from purchase.endaoment import EndaomentService
from purchase.models import Fundraise
from purchase.related_models.constants.currency import RSC, USD
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.serializers.fundraise_overview_serializer import (
    FundraiseOverviewSerializer,
)
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.grant_overview_serializer import GrantOverviewSerializer
from purchase.serializers.purchase_serializer import DynamicPurchaseSerializer
from purchase.services.fundraise_service import FundraiseService
from referral.services.referral_bonus_service import ReferralBonusService
from user.permissions import IsModerator
from user.related_models.follow_model import Follow
from utils.sentry import log_error


class FundraiseViewSet(viewsets.ModelViewSet):
    queryset = Fundraise.objects.all()
    serializer_class = DynamicFundraiseSerializer
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.fundraise_service = kwargs.pop("fundraise_service", FundraiseService())
        self.endaoment_service = kwargs.pop("endaoment_service", EndaomentService())
        self.referral_bonus_service = kwargs.pop(
            "referral_bonus_service",
            ReferralBonusService(),
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

    @track_event
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
        if amount_currency not in (RSC, USD):
            return Response(
                {"message": "amount_currency must be RSC or USD"}, status=400
            )

        # Get fundraise
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        # Convert amount to appropriate type
        if amount_currency == USD:
            amount = int(amount)
        else:
            amount = Decimal(amount)

        # Create contribution via service
        contribution, error = self.fundraise_service.create_contribution(
            user=user,
            fundraise=fundraise,
            amount=amount,
            currency=amount_currency,
        )

        if error:
            return Response({"message": error}, status=400)

        # Let the contributor follow the preregistration
        document = fundraise.unified_document.get_document()
        Follow.objects.get_or_create(
            user=user,
            object_id=document.id,
            content_type=ContentType.objects.get_for_model(document),
        )

        # return updated fundraise object
        context = self.get_serializer_context()
        serializer = self.get_serializer(fundraise, context=context)
        return Response(serializer.data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def endaoment_reserve(self, request, *args, **kwargs):
        data = request.data
        user = request.user

        fundraise_id = kwargs.get("pk", None)
        origin_fund_id = data.get("origin_fund_id")
        amount_cents = data.get("amount_cents")

        if fundraise_id is None:
            return Response({"message": "fundraise_id is required"}, status=400)
        if not origin_fund_id:
            return Response({"message": "origin_fund_id is required"}, status=400)
        if amount_cents is None:
            return Response({"message": "amount_cents is required"}, status=400)

        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        # User must have an Endaoment connection
        if not self.endaoment_service.get_valid_access_token(user):
            return Response(
                {"message": "Endaoment connection required"},
                status=400,
            )

        _, error = self.fundraise_service.create_endaoment_reservation(
            user=user,
            fundraise=fundraise,
            amount_cents=amount_cents,
            origin_fund_id=origin_fund_id,
        )
        if error:
            return Response({"message": error}, status=400)

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

            # Process referral bonuses for completed fundraise
            try:
                self.referral_bonus_service.process_fundraise_completion(fundraise)
            except Exception as e:
                log_error(e, message="Failed to process referral bonuses")

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
        result = self.fundraise_service.close_fundraise(fundraise)

        if result:
            # Return updated fundraise object
            context = self.get_serializer_context()
            serializer = self.get_serializer(fundraise, context=context)
            return Response(serializer.data)
        else:
            return Response(
                {
                    "message": (
                        "Failed to close fundraise. It may already be closed or "
                        "have no funds to refund."
                    )
                },
                status=400,
            )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def funder_overview(self, request, *args, **kwargs):
        """Return funder overview metrics for the authenticated user."""
        data = self.fundraise_service.get_funder_overview(request.user)
        serializer = FundraiseOverviewSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def grant_overview(self, request, *args, **kwargs):
        """Return metrics for a specific grant."""
        grant_id = request.query_params.get("grant_id")
        if not grant_id:
            return Response({"error": "grant_id is required"}, status=400)
        data = self.fundraise_service.get_grant_overview(request.user, int(grant_id))
        serializer = GrantOverviewSerializer(data)
        return Response(serializer.data)
