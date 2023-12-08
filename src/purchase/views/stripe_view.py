
import stripe
from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from notification.models import Notification
from purchase.models import (
    Wallet,
)
from purchase.serializers import (
    WalletSerializer,
)
from researchhub.settings import BASE_FRONTEND_URL
from user.models import Action, Author


class StripeViewSet(viewsets.ModelViewSet):
    # Deprecated
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = []
    throttle_classes = []

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def onboard_stripe_account(self, request):
        user = request.user
        wallet = user.author_profile.wallet

        if not wallet.stripe_acc or not wallet.stripe_verified:
            acc = stripe.Account.create(
                type="express",
                country="US",  # This is where our business resides
                email=user.email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            )

            wallet.stripe_acc = acc["id"]
            wallet.save()
        elif wallet:
            account_links = stripe.Account.create_login_link(wallet.stripe_acc)
            return Response(account_links, status=200)

        refresh_url = request.data["refresh_url"]
        return_url = request.data["return_url"]

        try:
            account_links = stripe.AccountLink.create(
                account=wallet.stripe_acc,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
        except Exception as e:
            return Response(e, status=400)
        return Response(account_links, status=200)

    @action(detail=True, methods=["get"])
    def verify_stripe_account(self, request, pk=None):
        author = Author.objects.get(id=pk)
        wallet = author.wallet
        stripe_id = wallet.stripe_acc
        acc = stripe.Account.retrieve(stripe_id)

        redirect = f"{BASE_FRONTEND_URL}/user/{pk}/stripe?verify_stripe=true"
        account_links = stripe.Account.create_login_link(
            stripe_id, redirect_url=redirect
        )

        if acc["charges_enabled"]:
            wallet.stripe_verified = True
            wallet.save()
            return Response({**account_links}, status=200)

        return Response(
            {
                "reason": "Please complete verification via Stripe Dashboard",
                **account_links,
            },
            status=200,
        )

    @action(detail=False, methods=["post"])
    def stripe_capability_updated(self, request):
        data = request.data
        acc_id = data["account"]
        acc_obj = data["data"]["object"]
        status = acc_obj["status"]
        capability_type = acc_obj["id"]
        requirements = acc_obj["requirements"]
        currently_due = requirements["currently_due"]

        id_due = "individual.id_number" in currently_due
        id_verf_due = "individual.verification.document" in currently_due

        if capability_type != "transfers" or status == "pending":
            return Response(status=200)

        wallet = self.queryset.get(stripe_acc=acc_id)
        user = wallet.author.user
        if status == "active" and not wallet.stripe_verified:
            account_links = stripe.Account.create_login_link(acc_id)
            wallet.stripe_verified = True
            wallet.save()
            self._send_stripe_notification(
                user, status, "Your Stripe account has been verified", **account_links
            )
        elif status == "active" and wallet.stripe_verified:
            return Response(status=200)

        if not id_due and not id_verf_due and not len(currently_due) <= 2:
            return Response(status=200)

        try:
            account_links = stripe.Account.create_login_link(acc_id)
        except Exception as e:
            return Response(e, status=200)

        message = ""
        if id_due:
            message = """
                Social Security Number or other
                government identification
            """
        elif id_verf_due:
            message = """
                Documents pertaining to government
                identification
            """

        self._send_stripe_notification(user, status, message, **account_links)
        return Response(status=200)

    def _send_stripe_notification(self, user, status, message, **kwargs):
        user_id = user.id
        user_type = ContentType.objects.get(model="user")
        action = Action.objects.create(
            user=user,
            content_type=user_type,
            object_id=user_id,
        )
        notification = Notification.objects.create(
            recipient=user,
            action_user=user,
            action=action,
        )

        notification.send_notification()
