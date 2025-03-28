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
        # Get all contributions in a single query with prefetched user data
        contributions = fundraise.purchases.select_related("user").order_by(
            "-created_date"
        )

        # Process all contributions to build user data
        user_data = {}
        for contribution in contributions:
            user_id = contribution.user_id
            amount = float(contribution.amount)

            if user_id not in user_data:
                user_data[user_id] = {
                    "user": contribution.user,
                    "total": 0,
                    "contributions": [],
                }

            # Add to running total
            user_data[user_id]["total"] += amount

            # Add contribution details
            user_data[user_id]["contributions"].append(
                {"amount": amount, "date": contribution.created_date}
            )

        # Serialize users
        context = self.context
        _context_fields = context.get("pch_dfs_get_contributors", {})

        result = []
        for user_id, data in user_data.items():
            # Serialize the user
            serializer = DynamicUserSerializer(
                data["user"], context=context, **_context_fields
            )
            user_result = serializer.data

            # Add contribution data
            user_result["total_contribution"] = data["total"]
            user_result["contributions"] = data["contributions"]
            result.append(user_result)

        # Sort by total contribution (descending)
        result = sorted(result, key=lambda x: x["total_contribution"], reverse=True)

        return {
            "total": len(user_data),
            "top": result,  # Keep original key for backward compatibility
        }
