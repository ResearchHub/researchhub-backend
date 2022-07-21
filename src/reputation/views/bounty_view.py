import decimal
import time

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from purchase.models import Balance
from reputation.distributions import (
    create_bounty_dao_fee_distribution,
    create_bounty_rh_fee_distribution,
)
from reputation.distributor import Distributor
from reputation.models import Bounty, Escrow, Term
from reputation.permissions import UserBounty
from reputation.serializers import (
    BountySerializer,
    BountySolutionSerializer,
    DynamicBountySerializer,
    EscrowSerializer,
)
from user.models import User
from utils.permissions import CreateOnly


class BountyViewSet(viewsets.ModelViewSet):
    queryset = Bounty.objects.all()
    serializer_class = BountySerializer
    permission_classes = [IsAuthenticated, CreateOnly | AllowAny]
    ALLOWED_CREATE_CONTENT_TYPES = ("researchhubunifieddocument",)
    ALLOWED_APPROVE_CONTENT_TYPES = ("thread", "comment", "reply")

    def _get_rh_fee_recipient(self):
        user = User.objects.filter(email="placeholder_1@researchhub.com")
        if user.exists():
            return user.first()

        user = User.objects.filter(email="bank@researchhub.com")
        if user.exists():
            return user.first()
        return User.objects.get(id=1)

    def _get_dao_fee_recipient(self):
        user = User.objects.filter(email="placeholder_2@researchhub.com")
        if user.exists():
            return user.first()

        user = User.objects.filter(email="bank@researchhub.com")
        if user.exists():
            return user.first()
        return User.objects.get(id=1)

    def _deduct_fee(self, user, gross_amount):
        current_term = Term.objects.last()
        rh_pct = current_term.rh_pct
        dao_pct = current_term.dao_pct
        rh_fee = gross_amount * rh_pct
        dao_fee = gross_amount * dao_pct
        fee = rh_fee + dao_fee
        net_amount = gross_amount - fee

        rh_recipient = self._get_rh_fee_recipient()
        dao_recipient = self._get_dao_fee_recipient()
        rh_fee_distribution = create_bounty_rh_fee_distribution(rh_fee)
        dao_fee_distribution = create_bounty_dao_fee_distribution(dao_fee)
        distributor_1 = Distributor(
            rh_fee_distribution, rh_recipient, current_term, time.time(), giver=user
        )
        record_1 = distributor_1.distribute()
        distributor_2 = Distributor(
            dao_fee_distribution, dao_recipient, current_term, time.time(), giver=user
        )
        record_2 = distributor_2.distribute()

        if not (record_1 and record_2):
            raise Exception("Failed to deduct fee")
        return net_amount, fee

    def _get_create_context(self):
        context = {
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile",)},
            "usr_dus_get_author_profile": {
                "_include_fields": ("id", "first_name", "last_name")
            },
        }
        return context

    def create(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        item_content_type = data.get("item_content_type", "")

        try:
            amount = decimal.Decimal(str(data.get("amount", "0")))
        except Exception as e:
            return Response(str(e), status=400)

        user_balance = user.get_balance()
        if amount <= 0 or user_balance - amount < 0:
            return Response({"error": "Insufficient Funds"}, status=402)
        elif amount <= 50 or amount > 1000000:
            return Response({"error": "Invalid amount"}, status=400)

        if item_content_type not in self.ALLOWED_CREATE_CONTENT_TYPES:
            return Response({"error": "Invalid content type"}, status=400)

        with transaction.atomic():
            net_amount, fee = self._deduct_fee(user, amount)
            content_type_id = ContentType.objects.get(model=item_content_type).id
            escrow_data = {
                "created_by": user.id,
                "hold_type": Escrow.BOUNTY,
                "amount": net_amount,
                "object_id": data.get("item_object_id", 0),
                "content_type": content_type_id,
            }
            escrow_serializer = EscrowSerializer(data=escrow_data)
            escrow_serializer.is_valid(raise_exception=True)
            escrow = escrow_serializer.save()

            data["created_by"] = user.id
            data["amount"] = net_amount
            data["item_content_type"] = content_type_id
            data["escrow"] = escrow.id
            bounty_serializer = BountySerializer(data=data)
            bounty_serializer.is_valid(raise_exception=True)
            bounty = bounty_serializer.save()

            amount_str = net_amount.to_eng_string()
            fee_str = fee.to_eng_string()
            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Bounty),
                object_id=bounty.id,
                amount=f"-{fee_str}",
            )
            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Term),
                object_id=bounty.id,
                amount=f"-{amount_str}",
            )

            context = self._get_create_context()
            serializer = DynamicBountySerializer(
                bounty,
                context=context,
                _include_fields=(
                    "amount",
                    "created_date",
                    "created_by",
                    "expiration_date",
                    "id",
                    "status",
                ),
            )
            return Response(serializer.data, status=201)

    @action(
        detail=True, methods=["post"], permission_classes=[IsAuthenticated, UserBounty]
    )
    def approve_bounty(self, request, pk=None):
        data = request.data
        amount = data.get("amount", None)
        recipient = data.get("recipient", None)
        content_type = data.get("content_type", None)
        object_id = data.get("object_id", None)

        if amount:
            try:
                amount = decimal.Decimal(str(amount))
            except Exception as e:
                return Response(str(e), status=400)

        if (amount and amount <= 0) or not recipient or not object_id:
            return Response(status=400)

        if content_type not in self.ALLOWED_APPROVE_CONTENT_TYPES:
            return Response({"error": "Invalid content type"}, status=400)

        with transaction.atomic():
            bounty = self.get_object()

            if bounty.status != Bounty.OPEN:
                return Response({"error": "Bounty is closed."}, status=400)

            content_type = ContentType.objects.get(model=content_type)
            model_class = content_type.model_class()
            solution = model_class.objects.get(id=object_id)
            escrow = bounty.escrow
            escrow.recipient_id = recipient
            bounty_paid = bounty.approve(payout_amount=amount)
            escrow.save()
            bounty.save()

            data["bounty"] = bounty.id
            data["created_by"] = solution.created_by.id
            data["content_type"] = content_type.id
            solution_serializer = BountySolutionSerializer(data=data)
            solution_serializer.is_valid(raise_exception=True)
            solution_serializer.save()
            if bounty_paid:
                serializer = self.get_serializer(bounty)
                return Response(serializer.data, status=200)
            else:
                raise Exception("Bounty payout error")

    # TODO: Delete
    def potential_approve_bounty(self, request):
        data = request.data
        content_type = data.get("content_type", "")
        object_id = data.get("object_id", 0)

        if not (content_type and object_id):
            return Response(status=400)

        with transaction.atomic():
            model_class = ContentType.objects.get(model=content_type).model_class()
            obj = model_class.objects.get(id=object_id)
            bounties = obj.bounties.all().order_by("-created_date")
            for bounty in bounties.iterator():
                bounty.approve()

    @action(
        detail=True,
        methods=["post", "delete"],
        permission_classes=[IsAuthenticated, UserBounty],
    )
    def cancel_bounty(self, request, pk=None):
        with transaction.atomic():
            bounty = self.get_object()
            if bounty.status != Bounty.OPEN:
                return Response(status=400)

            bounty_cancelled = bounty.cancel()
            bounty.save()
            if bounty_cancelled:
                serializer = self.get_serializer(bounty)
                return Response(serializer.data, status=200)
            else:
                raise Exception("Bounty cancel error")
