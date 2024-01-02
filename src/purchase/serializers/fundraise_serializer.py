from django.db import models
from rest_framework import serializers

from purchase.models import Fundraise
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.serializers.escrow_serializer import DynamicEscrowSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from user.models import User
from user.serializers import DynamicUserSerializer


class FundraiseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fundraise
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicFundraiseSerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    escrow = serializers.SerializerMethodField()
    amount_raised = serializers.SerializerMethodField()
    goal_amount = serializers.SerializerMethodField()
    contributors = serializers.SerializerMethodField()

    class Meta:
        model = Fundraise
        fields = "__all__"

    def get_created_by(self, fundraise):
        context = self.context
        _context_fields = context.get("pch_dfs_get_created_by", {})
        serializer = DynamicUserSerializer(
            fundraise.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_escrow(self, fundraise):
        context = self.context
        _context_fields = context.get("pch_dfs_get_escrow", {})
        serializer = DynamicEscrowSerializer(
            fundraise.escrow, context=context, **_context_fields
        )
        return serializer.data

    def get_amount_raised(self, fundraise):
        return {
            "usd": fundraise.get_amount_raised(currency=USD),
            "rsc": fundraise.get_amount_raised(currency=RSC),
        }

    def get_goal_amount(self, fundraise):
        usd_goal = fundraise.goal_amount
        usd_goal = float(usd_goal)
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
        return {
            "usd": usd_goal,
            "rsc": rsc_goal,
        }

    def get_contributors(self, fundraise):
        # Aggregate contributions by user and order by total contribution amount
        top_contributors = (
            fundraise.purchases.values("user_id")
            .annotate(
                amount_decimal=models.functions.Cast(
                    "amount", models.DecimalField(max_digits=19, decimal_places=10)
                )
            )
            .annotate(
                total_amount=models.Sum(
                    "amount_decimal"
                )  # Assuming amount_decimal is a field in Purchase
            )
            .order_by("-total_amount")[:3]
        )  # Selecting top 3

        # Fetch user instances for top contributors
        user_ids = [contributor["user_id"] for contributor in top_contributors]
        top_3_users = User.objects.filter(id__in=user_ids)

        # Serialize the user data
        context = self.context
        _context_fields = context.get("pch_dfs_get_contributors", {})
        serializer = DynamicUserSerializer(
            top_3_users, many=True, context=context, **_context_fields
        )

        total_contributors = fundraise.purchases.values("user").distinct().count()

        return {
            "total": total_contributors,
            "top": serializer.data,
        }
