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
        # Get all RSC contributions
        rsc_contributions = fundraise.purchases.select_related("user").order_by(
            "-created_date"
        )

        # Get all USD contributions
        usd_contributions = (
            fundraise.usd_contributions.select_related("user")
            .filter(is_refunded=False)
            .order_by("-created_date")
        )

        # Build user data lookup from all contributions
        user_data = {}
        for contribution in list(rsc_contributions) + list(usd_contributions):
            user_id = contribution.user_id
            if user_id not in user_data:
                user_data[user_id] = {
                    "user": contribution.user,
                    "total_rsc": 0,
                    "total_usd": 0,
                    "contributions": [],
                }

        # Process RSC contributions
        for contribution in rsc_contributions:
            amount = float(contribution.amount)
            user_data[contribution.user_id]["total_rsc"] += amount
            user_data[contribution.user_id]["contributions"].append(
                {"amount": amount, "currency": RSC, "date": contribution.created_date}
            )

        # Process USD contributions
        for contribution in usd_contributions:
            amount = contribution.amount_cents / 100.0
            user_data[contribution.user_id]["total_usd"] += amount
            user_data[contribution.user_id]["contributions"].append(
                {"amount": amount, "currency": USD, "date": contribution.created_date}
            )

        # Serialize users
        context = self.context
        _context_fields = context.get("pch_dfs_get_contributors", {})

        result = []
        for user_id, data in user_data.items():
            serializer = DynamicUserSerializer(
                data["user"], context=context, **_context_fields
            )
            user_result = serializer.data
            user_result["total_contribution"] = {
                "rsc": data["total_rsc"],
                "usd": data["total_usd"],
            }
            # Sort contributions by date descending
            user_result["contributions"] = sorted(
                data["contributions"], key=lambda x: x["date"], reverse=True
            )
            result.append(user_result)

        # Sort by total USD equivalent (descending)
        result = sorted(
            result,
            key=lambda x: x["total_contribution"]["usd"]
            + RscExchangeRate.rsc_to_usd(x["total_contribution"]["rsc"]),
            reverse=True,
        )

        return {
            "total": len(user_data),
            "top": result,  # Keep original key for backward compatibility
        }
