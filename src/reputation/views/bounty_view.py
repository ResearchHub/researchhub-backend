import decimal
import time

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.shortcuts import get_object_or_404
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
from reputation.models import Bounty, BountyFee, Contribution, Escrow
from reputation.permissions import UserCanApproveBounty, UserCanCancelBounty
from reputation.serializers import (
    BountySerializer,
    BountySolutionSerializer,
    DynamicBountySerializer,
    EscrowSerializer,
)
from reputation.tasks import create_contribution
from researchhub_document.related_models.constants.document_type import (
    ALL,
    BOUNTY,
    FILTER_BOUNTY_CLOSED,
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
)
from researchhub_document.utils import reset_unified_document_cache
from user.models import User
from utils.permissions import PostOnly
from utils.sentry import log_error


def _create_bounty_checks(user, amount, item_content_type, bypass_user_balance=False):
    try:
        amount = decimal.Decimal(amount)
    except Exception as e:
        log_error(e)
        return Response({"detail": "Invalid amount"}, status=400)

    user_balance = user.get_balance()
    fee_amount, rh_fee, dao_fee, current_bounty_fee = _calculate_fees(amount)
    if (
        amount <= 0
        or user_balance - (amount + fee_amount) < 0
        and not bypass_user_balance
    ):
        return Response({"detail": "Insufficient Funds"}, status=402)
    elif amount <= 50 or amount > 1000000:
        return Response({"detail": "Invalid amount. Minimum of 50 RSC"}, status=400)

    if item_content_type not in BountyViewSet.ALLOWED_CREATE_CONTENT_TYPES:
        return Response({"detail": "Invalid content type"}, status=400)

    return (amount, fee_amount, rh_fee, dao_fee, current_bounty_fee)


def _calculate_fees(gross_amount):
    current_bounty_fee = BountyFee.objects.last()
    rh_pct = current_bounty_fee.rh_pct
    dao_pct = current_bounty_fee.dao_pct
    rh_fee = gross_amount * rh_pct
    dao_fee = gross_amount * dao_pct
    fee = rh_fee + dao_fee

    return fee, rh_fee, dao_fee, current_bounty_fee


def _deduct_fees(user, fee, rh_fee, dao_fee, current_bounty_fee):
    rh_recipient = User.objects.get_revenue_account()
    dao_recipient = User.objects.get_community_account()
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


def _create_bounty(
    user,
    data,
    amount,
    fee_amount,
    current_bounty_fee,
    item_content_type,
    item_object_id,
    balance_required=True,
):
    content_type = ContentType.objects.get(model=item_content_type)
    content_type_id = content_type.id
    model_class = content_type.model_class()
    obj = model_class.objects.get(id=item_object_id)
    unified_document = obj.unified_document

    # Check if there is an existing bounty open on the object
    parent_bounty_id = None
    existing_bounties = Bounty.objects.filter(
        status=Bounty.OPEN,
        item_content_type=content_type,
        item_object_id=item_object_id,
    )
    if existing_bounties.exists():
        parent = existing_bounties.first()
        parent_bounty_id = parent.id
        escrow = parent.escrow
        escrow.amount_holding += amount
        escrow.save()
        data["expiration_date"] = parent.expiration_date
    else:
        escrow_data = {
            "created_by": user.id,
            "hold_type": Escrow.BOUNTY,
            "amount_holding": amount,
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
    data["unified_document"] = unified_document.id
    data["parent"] = parent_bounty_id
    bounty_serializer = BountySerializer(data=data)
    bounty_serializer.is_valid(raise_exception=True)
    bounty = bounty_serializer.save()

    amount_str = amount.to_eng_string()
    fee_str = fee_amount.to_eng_string()

    if balance_required:
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
    return bounty


class BountyViewSet(viewsets.ModelViewSet):
    queryset = Bounty.objects.all()
    serializer_class = BountySerializer
    permission_classes = [IsAuthenticated, PostOnly]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["item_content_type__model", "item_object_id", "status"]

    ALLOWED_CREATE_CONTENT_TYPES = ("rhcommentmodel", "thread")
    ALLOWED_APPROVE_CONTENT_TYPES = ("rhcommentmodel", "thread", "comment", "reply")

    def _get_create_context(self):
        context = {
            "rep_dbs_get_created_by": {"_include_fields": ("author_profile", "id")},
            "rep_dbs_get_parent": {"_include_fields": ("id",)},
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "is_verified",
                )
            },
        }
        return context

    def _get_retrieve_context(self):
        context = self._get_create_context()
        context["rep_dbs_get_item"] = {
            "_include_fields": (
                "id",
                "comment_content_json",
            )
        }
        context["rep_dbs_get_unified_document"] = {
            "_include_fields": ("documents", "id", "document_type")
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
        context["rhc_dcs_get_created_by"] = {"_include_fields": ("author_profile",)}
        return context

    @track_event
    def create(self, request, *args, **kwargs):
        data = request.data
        user = request.user
        item_content_type = data.get("item_content_type", "")
        item_object_id = data.get("item_object_id", 0)
        amount = str(data.get("amount", "0"))

        response = _create_bounty_checks(user, amount, item_content_type)
        if not isinstance(response, tuple):
            return response
        else:
            amount, fee_amount, rh_fee, dao_fee, current_bounty_fee = response

        with transaction.atomic():
            _deduct_fees(user, fee_amount, rh_fee, dao_fee, current_bounty_fee)
            bounty = _create_bounty(
                user,
                data,
                amount,
                fee_amount,
                current_bounty_fee,
                item_content_type,
                item_object_id,
            )
            unified_document = bounty.unified_document

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
                    "parent",
                    "status",
                ),
            )
            create_contribution.apply_async(
                (
                    Contribution.BOUNTY_CREATED,
                    {"app_label": "reputation", "model": "bounty"},
                    user.id,
                    unified_document.id,
                    bounty.id,
                ),
                priority=1,
                countdown=10,
            )

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
                document_type=[ALL.lower(), BOUNTY.lower()],
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
        with transaction.atomic():
            bounty = self.get_object()
            if bounty.parent:
                bounty = bounty.parent

            unified_document = bounty.unified_document
            for solution in data:
                amount = solution.get("amount", 0)
                content_type = solution.get("content_type")
                object_id = solution.get("object_id")

                if content_type not in self.ALLOWED_APPROVE_CONTENT_TYPES:
                    raise Exception({"detail": "Invalid content type"})

                try:
                    decimal_amount = decimal.Decimal(str(amount))
                except Exception as e:
                    log_error(e)
                    raise Exception({"detail": "Invalid amount"})

                if decimal_amount <= 0 or not object_id:
                    raise Exception({"detail": "Bad request"})

                content_type_model = ContentType.objects.get(model=content_type)
                model_class = content_type_model.model_class()
                solution_obj = get_object_or_404(model_class, pk=object_id)
                solution_created_by = solution_obj.created_by

                solution_data = {
                    "bounty": bounty.id,
                    "created_by": solution_created_by.id,
                    "content_type": content_type_model.id,
                    "object_id": object_id,
                }
                solution_serializer = BountySolutionSerializer(data=solution_data)
                solution_serializer.is_valid(raise_exception=True)
                solution_obj = solution_serializer.save()
                bounty_paid = bounty.approve(
                    recipient=solution_created_by, payout_amount=decimal_amount
                )

                if not bounty_paid:
                    # Exception is raised to rollback database transaction
                    raise Exception("Bounty not paid to recipient")

                create_contribution.apply_async(
                    (
                        Contribution.BOUNTY_SOLUTION,
                        {"app_label": "reputation", "model": "bountysolution"},
                        solution_created_by.id,
                        unified_document.id,
                        solution_obj.id,
                    ),
                    priority=1,
                    countdown=10,
                )

            bounty_closed = bounty.close(Bounty.CLOSED)
            if not bounty_closed:
                # Exception is raised to rollback database transaction
                raise Exception("Bounty failed to close")

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
                document_type=[ALL.lower(), BOUNTY.lower()],
                with_default_hub=True,
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
                    "parent",
                    "status",
                ),
            )
            return Response(serializer.data, status=200)

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
                return Response({"error": "Bounty is not open."}, status=400)

            if bounty.parent is not None:
                return Response({"error": "Please close parent bounty"}, status=400)

            bounty_cancelled = bounty.close(Bounty.CANCELLED)
            bounty.save()

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
                document_type=[ALL.lower(), BOUNTY.lower()],
                with_default_hub=True,
            )

            if bounty_cancelled:
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
                        "parent",
                        "status",
                    ),
                )
                serializer = self.get_serializer(bounty)
                return Response(serializer.data, status=200)
            else:
                # Exception is raised to rollback database transaction
                raise Exception("Bounty cancel error")

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
    )
    def get_bounties(self, request):
        qs = self.filter_queryset(self.get_queryset()).filter(
            parent__isnull=True, unified_document__is_removed=False
        )[:10]

        context = self._get_retrieve_context()
        serializer = DynamicBountySerializer(
            qs,
            many=True,
            _include_fields=(
                "created_by",
                "content_type",
                "id",
                "item",
                "expiration_date",
                "status",
                "total_amount",
                "unified_document",
            ),
            context=context,
        )
        return Response(serializer.data, status=200)
