import decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from purchase.models import Balance
from reputation.models import Bounty, Escrow
from reputation.serializers import BountySerializer, EscrowSerializer
from researchhub_document.models import ResearchhubUnifiedDocument


class BountyViewSet(viewsets.ModelViewSet):
    queryset = Bounty.objects.all()
    serializer_class = BountySerializer
    # TODO: Permissions
    permission_classes = [IsAuthenticated | AllowAny]

    def create(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        amount = decimal.Decimal(data.get("amount", 0))
        content_type_id = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        ).id

        user_balance = user.get_balance()
        if amount <= 0 or user_balance - amount < 0:
            return Response("Insufficient Funds", status=402)
        elif amount <= 50 or amount > 1000000:
            return Response(status=400)

        with transaction.atomic():

            escrow_data = {
                "created_by": user.id,
                "hold_type": Escrow.BOUNTY,
                "amount": amount,
                "object_id": data.get("item_object_id", 0),
                "content_type": content_type_id,
            }
            escrow_serializer = EscrowSerializer(data=escrow_data)
            escrow_serializer.is_valid(raise_exception=True)
            escrow = escrow_serializer.save()

            data["created_by"] = user.id
            data["amount"] = amount
            data["item_content_type"] = content_type_id
            data["escrow"] = escrow.id
            res = super().create(request, *args, **kwargs)
            amount_str = amount.to_eng_string()
            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Bounty),
                object_id=res.data["id"],
                amount=f"-{amount_str}",
            )
            return res

    # TODO: Permissions
    @action(detail=True, methods=["post"])
    def approve_bounty(self, request, pk=None):
        data = request.data
        amount = data.get("amount", None)
        recipient = data.get("recipient", None)
        solution_object_id = data.get("solution_object_id", None)
        solution_content_type = data.get("solution_content_type", None)

        if amount:
            amount = decimal.Decimal(amount)

        if (
            (amount and amount <= 0)
            or not recipient
            or not solution_object_id
            or not solution_content_type
        ):
            return Response(status=400)

        with transaction.atomic():
            bounty = self.get_object()

            if bounty.status != Bounty.OPEN:
                return Response(status=400)

            solution_content_type = ContentType.objects.get(model=solution_content_type)
            bounty.solution_content_type = solution_content_type
            bounty.solution_object_id = solution_object_id
            escrow = bounty.escrow
            escrow.recipient_id = recipient
            bounty_paid = bounty.approve(payout_amount=amount)
            escrow.save()
            bounty.save()
            if bounty_paid:
                return Response(status=200)
            else:
                raise Exception("Error")
                # return Response(status=400)

    # TODO: Permissions
    @action(detail=False, methods=["post"])
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

    # TODO: Permissions
    @action(detail=True, methods=["post", "delete"])
    def cancel_bounty(self, request, pk=None):
        with transaction.atomic():
            bounty = self.get_object()
            if bounty.status != Bounty.OPEN:
                return Response(status=400)

            bounty_cancelled = bounty.cancel()
            bounty.save()
            if bounty_cancelled:
                return Response(status=200)
            else:
                raise Exception("Error")
