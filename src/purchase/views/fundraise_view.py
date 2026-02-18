from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from purchase.models import Fundraise
from purchase.related_models.constants.currency import RSC, USD
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.serializers.funding_impact_serializer import FundingImpactSerializer
from purchase.serializers.funding_overview_serializer import FundingOverviewSerializer
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.purchase_serializer import DynamicPurchaseSerializer
from purchase.services.fundraise_service import FundraiseService
from purchase.services.funding_impact_service import FundingImpactService
from purchase.services.funding_overview_service import FundingOverviewService
from referral.services.referral_bonus_service import ReferralBonusService
from user.models import User
from user.permissions import IsModerator
from user.related_models.follow_model import Follow

#Temporary function for testing different user data, will be removed before release
def _resolve_target_user(request) -> User | None:
    """Return the user specified by ?user_id, falling back to the requester."""
    user_id = request.query_params.get("user_id")
    if user_id:
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
    return request.user


class FundraiseViewSet(viewsets.ModelViewSet):
    queryset = Fundraise.objects.all()
    serializer_class = DynamicFundraiseSerializer
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.fundraise_service = kwargs.pop("fundraise_service", FundraiseService())
        self.funding_impact_service = kwargs.pop("funding_impact_service", FundingImpactService())
        self.funding_overview_service = kwargs.pop("funding_overview_service", FundingOverviewService())
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
        origin_fund_id = data.get("origin_fund_id") or None

        # Validate body
        if fundraise_id is None:
            return Response({"message": "fundraise_id is required"}, status=400)
        if amount is None:
            return Response({"message": "amount is required"}, status=400)
        if amount_currency not in (RSC, USD):
            return Response(
                {"message": "amount_currency must be RSC or USD"}, status=400
            )
        if amount_currency == USD and not origin_fund_id:
            return Response(
                {"message": "origin_fund_id is required for USD contributions"},
                status=400,
            )
        if origin_fund_id and amount_currency != USD:
            return Response(
                {"message": "origin_fund_id requires USD amount_currency"},
                status=400,
            )

        # Get fundraise
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        if origin_fund_id:
            nonprofit_org = fundraise.get_nonprofit_org()
            if not nonprofit_org or not nonprofit_org.endaoment_org_id:
                return Response(
                    {"message": "Fundraise nonprofit org is not configured"},
                    status=400,
                )

        # Convert amount to appropriate type
        if amount_currency == USD:
            amount = int(amount)
        else:
            amount = Decimal(amount)

        # Create contribution via service
        _, error = self.fundraise_service.create_contribution(
            user=user,
            fundraise=fundraise,
            amount=amount,
            currency=amount_currency,
            origin_fund_id=origin_fund_id,
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
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        # Complete the fundraise via service
        try:
            self.fundraise_service.complete_fundraise(fundraise)
        except ValueError as e:
            return Response({"message": str(e)}, status=400)
        except RuntimeError as e:
            return Response({"message": str(e)}, status=500)

        # Return updated fundraise object
        context = self.get_serializer_context()
        serializer = self.get_serializer(fundraise, context=context)
        return Response(serializer.data)

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
    def funding_overview(self, request, *args, **kwargs):
        """Return funding overview metrics. Accepts optional ?user_id param."""
        user = _resolve_target_user(request)
        if user is None:
            return Response({"error": "User not found"}, status=404)
        data = self.funding_overview_service.get_funding_overview(user)
        serializer = FundingOverviewSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def funding_impact(self, request, *args, **kwargs):
        """Return funding impact metrics. Accepts optional ?user_id param."""
        user = _resolve_target_user(request)
        if user is None:
            return Response({"error": "User not found"}, status=404)
        data = self.funding_impact_service.get_funding_impact_overview(user)
        serializer = FundingImpactSerializer(data)
        return Response(serializer.data)
