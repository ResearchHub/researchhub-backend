import csv
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from purchase.models import Fundraise
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.purchase_serializer import DynamicPurchaseSerializer
from purchase.serializers.usd_fundraise_contribution_serializer import (
    UsdFundraiseContributionSerializer,
)
from purchase.services.fundraise_service import (
    USD_CONTRIBUTION_CSV_HEADERS,
    FundraiseService,
)
from referral.services.referral_bonus_service import ReferralBonusService
from user.permissions import IsModerator
from user.related_models.follow_model import Follow


class FundraiseViewSet(viewsets.ModelViewSet):
    queryset = Fundraise.objects.all()
    serializer_class = DynamicFundraiseSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options", "post"]

    def dispatch(self, request, *args, **kwargs):
        self.fundraise_service = kwargs.pop("fundraise_service", FundraiseService())
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
        use_credits = bool(data.get("use_credits", True))

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
            use_credits=use_credits,
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
        detail=False,
        permission_classes=[IsAuthenticated],
    )
    def usd_contributions(self, request, *args, **kwargs):
        """
        Return the authenticated user's USD fundraise contributions,
        ordered by most recent first.
        """
        contributions = (
            UsdFundraiseContribution.objects.for_user(request.user.id)
            .not_refunded()
            .select_related("fundraise")
            .order_by("-created_date")
        )

        page = self.paginate_queryset(contributions)
        if page is not None:
            serializer = UsdFundraiseContributionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = UsdFundraiseContributionSerializer(contributions, many=True)
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
    def reopen(self, request, *args, **kwargs):
        """
        Reopen a fundraise (status OPEN) and extend its end date by
        `duration_days` days from now. Only accessible to moderators.
        Cannot reopen fundraises that have already paid out (COMPLETED).
        """
        fundraise_id = kwargs.get("pk", None)

        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
        except Fundraise.DoesNotExist:
            return Response({"message": "Fundraise does not exist"}, status=400)

        raw_duration = request.data.get("duration_days")
        try:
            duration_days = int(raw_duration)
        except (TypeError, ValueError):
            return Response(
                {"message": "duration_days must be a positive integer"}, status=400
            )

        try:
            self.fundraise_service.reopen_fundraise(fundraise, duration_days)
        except ValueError as e:
            return Response({"message": str(e)}, status=400)

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

    @action(
        methods=["GET"],
        detail=True,
        permission_classes=[IsModerator],
        url_path="usd_contributions.csv",
    )
    def usd_contributions_csv(self, request, *args, **kwargs):
        """
        Export a CSV of USD contributions for a fundraise.
        Used for manual USD contribution payout/refund processing.
        """
        fundraise = get_object_or_404(
            Fundraise.objects.select_related("unified_document", "escrow"),
            id=kwargs.get("pk"),
        )

        rows = self.fundraise_service.export_usd_contributions(fundraise)

        filename = f"fundraise_{fundraise.id}_usd_contributions.csv"
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(USD_CONTRIBUTION_CSV_HEADERS)
        for row in rows:
            writer.writerow(row)

        return response
