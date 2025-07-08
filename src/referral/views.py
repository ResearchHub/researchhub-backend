from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from purchase.models import Purchase
from referral.models import ReferralSignup
from referral.serializers import (
    AddReferralCodeSerializer,
    ReferralMetricsSerializer,
    ReferralNetworkDetailSerializer,
    ReferralSignupSerializer,
)
from referral.services.referral_metrics_service import ReferralMetricsService
from reputation.related_models.distribution import Distribution
from user.models import User


class ReferralMetricsViewSet(viewsets.ViewSet):
    """
    ViewSet for referral metrics endpoints.

    Provides metrics about referral network funding power and activity.
    """

    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        """
        Get comprehensive referral metrics for the authenticated user.

        Returns:
            - Network funding power (deployed and potential)
            - Referral activity statistics
            - User's funding credits
            - Network earned credits
        """
        user = request.user
        service = ReferralMetricsService(user)
        metrics = service.get_comprehensive_metrics()

        serializer = ReferralMetricsSerializer(metrics)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_metrics(self, request):
        """
        Convenience endpoint to get current user's metrics without needing user ID.
        """
        user = request.user
        service = ReferralMetricsService(user)
        metrics = service.get_comprehensive_metrics()

        serializer = ReferralMetricsSerializer(metrics)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def network_details(self, request):
        """
        Get detailed information about each referred user in the network.

        Returns list of referred users with:
            - User information
            - Total funded amount
            - Referral bonuses earned
            - Activity status
        """
        user = request.user
        service = ReferralMetricsService(user)
        network_details = service.get_referral_network_details()

        serializer = ReferralNetworkDetailSerializer(network_details, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAdminUser])
    def user_metrics(self, request, pk=None):
        """
        Admin endpoint to view any user's referral metrics.

        Args:
            pk: User ID to get metrics for
        """
        try:

            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND
            )

        service = ReferralMetricsService(user)
        metrics = service.get_comprehensive_metrics()

        serializer = ReferralMetricsSerializer(metrics)
        return Response(
            {"user_id": user.id, "username": user.username, "metrics": serializer.data}
        )


class AggregateReferralMetricsViewSet(viewsets.ViewSet):
    """
    ViewSet for platform-wide aggregate referral metrics.
    Admin only.
    """

    permission_classes = [IsAdminUser]

    def list(self, request):
        """
        Get platform-wide referral metrics.

        Returns aggregate statistics about:
            - Total referrals made
            - Total referral bonuses distributed
            - Active referral networks
            - Top referrers
        """
        # Total referrals
        total_referrals = ReferralSignup.objects.count()

        # Active referrals (those who have made contributions)
        active_referrals = (
            ReferralSignup.objects.filter(
                referred__purchases__purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                referred__purchases__paid_status=Purchase.PAID,
            )
            .distinct()
            .count()
        )

        # Total referral bonuses distributed
        total_bonuses = (
            Distribution.objects.filter(
                distribution_type="REFERRAL_BONUS",
                distributed_status=Distribution.DISTRIBUTED,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        # Top referrers by number of successful referrals
        top_referrers = (
            ReferralSignup.objects.values("referrer__id", "referrer__username")
            .annotate(
                referral_count=Count("id"),
                active_referral_count=Count(
                    "id",
                    filter=Q(
                        referred__purchases__purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                        referred__purchases__paid_status=Purchase.PAID,
                    ),
                ),
            )
            .order_by("-referral_count")[:10]
        )

        return Response(
            {
                "total_referrals": total_referrals,
                "active_referrals": active_referrals,
                "total_bonuses_distributed": float(total_bonuses),
                "top_referrers": list(top_referrers),
            }
        )


class ReferralAssignmentViewSet(viewsets.ViewSet):
    """
    ViewSet for assigning referral codes to users.

    Allows adding referral codes to users who signed up recently (within the last hour)
    or retroactively for moderators.
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def add_referral_code(self, request):
        """
        Add a referral code to a user.

        For regular users:
        - Can only add referral codes to their own account
        - Can only add if they signed up within the last hour

        For moderators/admins:
        - Can add referral codes to any user
        - No time restrictions (can add retroactively)

        Request body:
        {
            "user_id": 123,
            "referral_code": "abc123..."
        }
        """
        serializer = AddReferralCodeSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user_id = serializer.validated_data["user_id"]
        referral_code = serializer.validated_data["referral_code"]

        try:
            referred_user = User.objects.get(id=user_id)
            referrer_user = User.objects.get(referral_code=referral_code)

            # Check if non-moderator is trying to add referral code for someone else
            if not request.user.is_staff and not request.user.moderator:
                if request.user.id != user_id:
                    return Response(
                        {
                            "detail": "You can only add referral codes to your own account."
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

                # Check time constraint for non-moderators
                one_hour_ago = timezone.now() - timedelta(hours=1)
                if referred_user.date_joined < one_hour_ago:
                    return Response(
                        {
                            "detail": "Can only add referral codes to users who joined within the last hour."
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

            # Create the referral signup
            referral_signup = ReferralSignup.objects.create(
                referrer=referrer_user, referred=referred_user
            )

            # Also update the invited_by field if not already set
            if not referred_user.invited_by:
                referred_user.invited_by = referrer_user
                referred_user.save()

            # Serialize and return the created referral signup
            response_serializer = ReferralSignupSerializer(referral_signup)
            return Response(
                {
                    "message": "Referral code successfully added.",
                    "referral_signup": response_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            return Response(
                {"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
