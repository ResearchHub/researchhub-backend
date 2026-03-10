from rest_framework import serializers

from purchase.models import Fundraise
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.serializers.escrow_serializer import DynamicEscrowSerializer
from researchhub.serializers import DynamicModelFieldSerializer
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
        aggregated = fundraise.get_contributors_summary()

        # Serialize users
        context = self.context
        _context_fields = context.get("pch_dfs_get_contributors", {})

        result = []
        for entry in aggregated.top:
            serializer = DynamicUserSerializer(
                entry.user, context=context, **_context_fields
            )
            user_result = serializer.data
            user_result["total_contribution"] = {
                "rsc": entry.total_rsc,
                "usd": entry.total_usd,
            }
            user_result["contributions"] = [
                {
                    "amount": contribution.amount,
                    "currency": contribution.currency,
                    "date": contribution.date,
                }
                for contribution in entry.contributions
            ]
            result.append(user_result)

        return {
            "total": aggregated.total,
            "top": result,  # Keep original key for backward compatibility
        }
