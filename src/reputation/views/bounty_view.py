import decimal
import time

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from purchase.models import Balance
from reputation.distributions import (
    create_bounty_dao_fee_distribution,
    create_bounty_rh_fee_distribution,
)
from reputation.distributor import Distributor
from reputation.models import Bounty, BountyFee, Escrow
from reputation.permissions import (
    SingleBountyOpen,
    UserCanApproveBounty,
    UserCanCancelBounty,
)
from reputation.serializers import (
    BountySerializer,
    BountySolutionSerializer,
    DynamicBountySerializer,
    EscrowSerializer,
)
from researchhub_document.related_models.constants.document_type import (
    ALL,
    FILTER_BOUNTY_CLOSED,
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
)
from researchhub_document.related_models.constants.filters import HOT
from researchhub_document.utils import reset_unified_document_cache
from user.models import User
from utils.permissions import CreateOnly


class BountyViewSet(viewsets.ModelViewSet):
    queryset = Bounty.objects.all()
    serializer_class = BountySerializer
    permission_classes = [IsAuthenticated, CreateOnly, SingleBountyOpen]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["item_object_id", "status"]

    ALLOWED_CREATE_CONTENT_TYPES = ("researchhubunifieddocument", "thread")
    ALLOWED_APPROVE_CONTENT_TYPES = ("thread", "comment", "reply")

    def _get_rh_fee_recipient(self):
        user = User.objects.filter(email="revenue@researchhub.com")
        if user.exists():
            return user.first()

        user = User.objects.filter(email="bank@researchhub.com")
        if user.exists():
            return user.first()
        return User.objects.get(id=1)

    def _get_dao_fee_recipient(self):
        user = User.objects.filter(email="community@researchhub.com")
        if user.exists():
            return user.first()

        user = User.objects.filter(email="bank@researchhub.com")
        if user.exists():
            return user.first()
        return User.objects.get(id=1)

    def _calculate_fees(self, gross_amount):
        current_bounty_fee = BountyFee.objects.last()
        rh_pct = current_bounty_fee.rh_pct
        dao_pct = current_bounty_fee.dao_pct
        rh_fee = gross_amount * rh_pct
        dao_fee = gross_amount * dao_pct
        fee = rh_fee + dao_fee

        return fee, rh_fee, dao_fee, current_bounty_fee

    def _deduct_fees(self, user, fee, rh_fee, dao_fee, current_bounty_fee):
        rh_recipient = self._get_rh_fee_recipient()
        dao_recipient = self._get_dao_fee_recipient()
        rh_fee_distribution = create_bounty_rh_fee_distribution(rh_fee)
        dao_fee_distribution = create_bounty_dao_fee_distribution(dao_fee)
        rh_inc_distributor = Distributor(
            rh_fee_distribution,
            rh_recipient,
            current_bounty_fee,
            time.time(),
            giver=user,
        )
        rh_inc_record = rh_inc_distributor.distribute()
        rh_dao_distributor = Distributor(
            dao_fee_distribution,
            dao_recipient,
            current_bounty_fee,
            time.time(),
            giver=user,
        )
        rh_dao_record = rh_dao_distributor.distribute()

        if not (rh_inc_record and rh_dao_record):
            raise Exception("Failed to deduct fee")
        return True

    def _get_create_context(self):
        context = {
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile", "id")},
            "usr_dus_get_author_profile": {
                "_include_fields": ("id", "first_name", "last_name")
            },
        }
        return context

    def _get_retrieve_context(self):
        context = self._get_create_context()
        context["rep_dbs_get_item"] = {
            "_include_fields": (
                "created_by",
                "documents",
                "document_type",
                "id",
                "plain_text",
                "unified_document",
            )
        }
        context["doc_duds_get_created_by"] = {"_include_fields": ("author_profile",)}
        context["doc_duds_get_documents"] = {
            "_include_fields": (
                "id",
                "slug",
                "title",
            )
        }
        context["dis_dts_get_created_by"] = {"_include_fields": ("author_profile",)}
        context["dis_dts_get_unified_document"] = {
            "_include_fields": ("documents", "document_type")
        }
        return context

    @track_event
    def create(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        item_content_type = data.get("item_content_type", "")
        item_object_id = data.get("item_object_id", 0)

        try:
            amount = decimal.Decimal(str(data.get("amount", "0")))
        except Exception as e:
            return Response(str(e), status=400)

        user_balance = user.get_balance()
        fee_amount, rh_fee, dao_fee, current_bounty_fee = self._calculate_fees(amount)
        if amount <= 0 or user_balance - (amount + fee_amount) < 0:
            return Response({"error": "Insufficient Funds"}, status=402)
        elif amount <= 50 or amount > 1000000:
            return Response({"error": "Invalid amount"}, status=400)

        if item_content_type not in self.ALLOWED_CREATE_CONTENT_TYPES:
            return Response({"error": "Invalid content type"}, status=400)

        with transaction.atomic():
            self._deduct_fees(user, fee_amount, rh_fee, dao_fee, current_bounty_fee)
            content_type = ContentType.objects.get(model=item_content_type)
            content_type_id = content_type.id

            if item_content_type == "researchhubunifieddocument":
                unified_document_id = item_object_id
            else:
                obj = content_type.model_class().objects.get(id=item_object_id)
                unified_document_id = obj.unified_document.id

            escrow_data = {
                "created_by": user.id,
                "hold_type": Escrow.BOUNTY,
                "amount": amount,
                "object_id": item_object_id,
                "content_type": content_type_id,
            }
            escrow_serializer = EscrowSerializer(data=escrow_data)
            escrow_serializer.is_valid(raise_exception=True)
            escrow = escrow_serializer.save()

            data["created_by"] = user.id
            data["amount"] = amount
            data["item_content_type"] = content_type_id
            data["escrow"] = escrow.id
            data["unified_document"] = unified_document_id
            bounty_serializer = BountySerializer(data=data)
            bounty_serializer.is_valid(raise_exception=True)
            bounty = bounty_serializer.save()

            amount_str = amount.to_eng_string()
            fee_str = fee_amount.to_eng_string()

            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(BountyFee),
                object_id=current_bounty_fee.id,
                amount=f"-{fee_str}",
            )

            Balance.objects.create(
                user=user,
                content_type=ContentType.objects.get_for_model(Bounty),
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
            unified_document = bounty.unified_document
            unified_document.update_filters(
                (
                    FILTER_BOUNTY_OPEN,
                    FILTER_HAS_BOUNTY,
                    SORT_BOUNTY_EXPIRATION_DATE,
                    SORT_BOUNTY_TOTAL_AMOUNT,
                )
            )
            hubs = list(unified_document.hubs.all().values_list("id", flat=True))
            reset_unified_document_cache(
                hub_ids=hubs,
                document_type=[ALL.lower()],
                filters=[HOT],
                with_default_hub=True,
            )
            return Response(serializer.data, status=201)

    @track_event
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, UserCanApproveBounty],
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

            unified_document = bounty.unified_document
            unified_document.update_filters(
                (
                    FILTER_BOUNTY_OPEN,
                    FILTER_BOUNTY_CLOSED,
                    SORT_BOUNTY_EXPIRATION_DATE,
                    SORT_BOUNTY_TOTAL_AMOUNT,
                )
            )

            hubs = list(unified_document.hubs.all().values_list("id", flat=True))
            reset_unified_document_cache(
                hub_ids=hubs,
                document_type=[ALL.lower()],
                filters=[HOT],
                with_default_hub=True,
            )
            if bounty_paid:
                serializer = self.get_serializer(bounty)
                return Response(serializer.data, status=200)
            else:
                raise Exception("Bounty payout error")

    @track_event
    @action(
        detail=True,
        methods=["post", "delete"],
        permission_classes=[IsAuthenticated, UserCanCancelBounty],
    )
    def cancel_bounty(self, request, pk=None):
        with transaction.atomic():
            bounty = self.get_object()
            if bounty.status != Bounty.OPEN:
                return Response(status=400)

            bounty_cancelled = bounty.cancel()
            bounty.save()
            bounties_closed = [bounty]
            # Cancel all group bounties if the cancel request is by the OP
            if request.user == bounty.item.created_by:
                all_bounties = bounty.item.bounties.filter(status=Bounty.OPEN)
                for cur_bounty in all_bounties:
                    cur_bounty.cancel()
                    cur_bounty.save()
                    bounties_closed.append(cur_bounty)

            unified_document = bounty.unified_document
            unified_document.update_filters(
                (
                    FILTER_BOUNTY_CLOSED,
                    SORT_BOUNTY_EXPIRATION_DATE,
                    SORT_BOUNTY_TOTAL_AMOUNT,
                )
            )

            hubs = list(unified_document.hubs.all().values_list("id", flat=True))
            reset_unified_document_cache(
                hub_ids=hubs,
                document_type=[ALL.lower()],
                filters=[HOT],
                with_default_hub=True,
            )

            if bounty_cancelled:
                serializer = self.get_serializer(bounties_closed, many=True)
                return Response(serializer.data, status=200)
            else:
                raise Exception("Bounty cancel error")

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        # permission_classes=[IsAuthenticated]
    )
    def get_bounties(self, request):
        status = self.request.GET.get("status")
        qs = self.get_queryset().filter(status=status).order_by("expiration_date")[:10]
        not_removed_posts = []
        for bounty in qs:
            if not bounty.item.is_removed:
                not_removed_posts.append(bounty)
        context = self._get_retrieve_context()
        serializer = DynamicBountySerializer(
            not_removed_posts,
            many=True,
            _include_fields=(
                "amount",
                "created_by",
                "content_type",
                "id",
                "item",
                "expiration_date",
                "status",
            ),
            context=context,
        )
        return Response(serializer.data, status=200)
