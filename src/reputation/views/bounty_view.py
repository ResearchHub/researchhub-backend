import decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from analytics.tasks import track_revenue_event
from purchase.models import Balance
from reputation.constants import MAXIMUM_BOUNTY_AMOUNT_RSC, MINIMUM_BOUNTY_AMOUNT_RSC
from reputation.models import Bounty, BountyFee, BountySolution, Contribution, Escrow
from reputation.permissions import UserCanApproveBounty, UserCanCancelBounty
from reputation.serializers import (
    BountySerializer,
    DynamicBountySerializer,
    EscrowSerializer,
)
from reputation.tasks import create_contribution
from reputation.utils import calculate_bounty_fees, deduct_bounty_fees
from researchhub_document.related_models.constants.document_type import (
    FILTER_BOUNTY_CLOSED,
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
)
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
    fee_amount, rh_fee, dao_fee, current_bounty_fee = calculate_bounty_fees(amount)
    if (
        amount <= 0
        or user_balance - (amount + fee_amount) < 0
        and not bypass_user_balance
    ):
        return Response({"detail": "Insufficient Funds"}, status=402)
    elif amount < MINIMUM_BOUNTY_AMOUNT_RSC or amount > MAXIMUM_BOUNTY_AMOUNT_RSC:
        return Response(
            {"detail": f"Invalid amount. Minimum of {MINIMUM_BOUNTY_AMOUNT_RSC} RSC"},
            status=400,
        )

    if item_content_type not in BountyViewSet.ALLOWED_CREATE_CONTENT_TYPES:
        return Response({"detail": "Invalid content type"}, status=400)

    return (amount, fee_amount, rh_fee, dao_fee, current_bounty_fee)


def _create_bounty(
    user,
    data,
    amount,
    fee_amount,
    current_bounty_fee,
    item_content_type,
    item_object_id,
    balance_required=True,
    rh_fee=None,
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

    # Track in Amplitude
    if rh_fee is not None:
        rh_fee_str = rh_fee.to_eng_string()
        track_revenue_event.apply_async(
            (
                user.id,
                "BOUNTY_FEE",
                rh_fee_str,
                None,
                "OFF_CHAIN",
                content_type.model,
                item_object_id,
            ),
            priority=1,
        )

    return bounty


class BountyViewSet(viewsets.ModelViewSet):
    queryset = Bounty.objects.all()
    serializer_class = BountySerializer
    permission_classes = [IsAuthenticated, PostOnly]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["item_content_type__model", "item_object_id", "status"]

    ALLOWED_CREATE_CONTENT_TYPES = ("rhcommentmodel", "thread", "researchhubpost")
    ALLOWED_APPROVE_CONTENT_TYPES = ("rhcommentmodel", "thread", "comment", "reply")

    def get_permissions(self):
        if self.action == "list":
            permission_classes = [AllowAny]
        else:
            permission_classes = self.permission_classes

        return [permission() for permission in permission_classes]

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
        if hasattr(self, "request"):
            context["request"] = self.request
        context["rep_dbs_get_item"] = {
            "_include_fields": (
                "id",
                "comment_content_json",
                "comment_content_type",
                "comment_type",
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
                "abstract",
                "authors",
            )
        }
        context["rep_dbs_get_hubs"] = {
            "_include_fields": ("id", "name", "namespace", "slug", "is_used_for_rep")
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

        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            response = _create_bounty_checks(user, amount, item_content_type)
            if not isinstance(response, tuple):
                return response
            else:
                amount, fee_amount, rh_fee, dao_fee, current_bounty_fee = response

            deduct_bounty_fees(user, fee_amount, rh_fee, dao_fee, current_bounty_fee)
            bounty = _create_bounty(
                user,
                data,
                amount,
                fee_amount,
                current_bounty_fee,
                item_content_type,
                item_object_id,
                rh_fee=rh_fee,
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

            # Validate total payout amount doesn't exceed bounty amount
            total_payout = sum(
                decimal.Decimal(str(solution.get("amount", 0))) for solution in data
            )
            if total_payout > bounty.amount:
                # Return 400 Bad Request instead of raising Exception
                return Response(
                    {"detail": "Total payout amount exceeds bounty amount"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            unified_document = bounty.unified_document
            bounty_solutions_to_process = []

            # First pass: Validate all solutions and find objects
            for solution in data:
                amount = solution.get("amount", 0)
                content_type_name = solution.get("content_type")
                object_id = solution.get("object_id")

                if content_type_name not in self.ALLOWED_APPROVE_CONTENT_TYPES:
                    return Response(
                        {"detail": f"Invalid content type: {content_type_name}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    decimal_amount = decimal.Decimal(str(amount))
                except Exception as e:
                    log_error(e)
                    return Response(
                        {"detail": f"Invalid amount: {amount}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if decimal_amount <= 0 or not object_id:
                    detail_msg = (
                        f"Bad request: Invalid amount ({decimal_amount}) "
                        f"or object_id ({object_id})"
                    )
                    return Response(
                        {"detail": detail_msg},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    content_type_model = ContentType.objects.get(
                        model=content_type_name
                    )
                except ContentType.DoesNotExist:
                    detail_msg = f"Content type model not found: {content_type_name}"
                    return Response(
                        {"detail": detail_msg},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                model_class = content_type_model.model_class()

                # Use get_object_or_404 to handle non-existent solutions gracefully
                try:
                    solution_obj = get_object_or_404(model_class, pk=object_id)
                except Http404:
                    detail_msg = (
                        f"Solution object not found: {content_type_name} "
                        f"with id {object_id}"
                    )
                    return Response(
                        {"detail": detail_msg},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                solution_created_by = solution_obj.created_by
                bounty_solutions_to_process.append(
                    {
                        "obj": solution_obj,
                        "created_by": solution_created_by,
                        "content_type_model": content_type_model,
                        "object_id": object_id,
                        "amount": decimal_amount,
                    }
                )

            # Second pass: Process validated solutions
            processed_solutions = []  # Keep track of successfully awarded solutions
            for solution_data in bounty_solutions_to_process:
                solution_created_by = solution_data["created_by"]
                content_type_model = solution_data["content_type_model"]
                object_id = solution_data["object_id"]
                decimal_amount = solution_data["amount"]

                # Get or create the solution record first
                bounty_solution, created = BountySolution.objects.get_or_create(
                    bounty=bounty,
                    created_by=solution_created_by,
                    content_type=content_type_model,
                    object_id=object_id,
                    defaults={
                        "status": BountySolution.Status.SUBMITTED
                    },  # Initial status
                )

                # Optional: Add logic here to handle already awarded solutions if needed
                # e.g., if bounty_solution.status == BountySolution.Status.AWARDED:
                #    continue # Or raise an error, depending on desired behavior

                # Attempt to pay out the bounty
                bounty_paid = bounty.approve(
                    recipient=solution_created_by, payout_amount=decimal_amount
                )

                if not bounty_paid:
                    # Exception is raised to rollback database transaction
                    error_msg = (
                        f"Bounty (id: {bounty.id}) payment failed for recipient "
                        f"(id: {solution_created_by.id}) amount {decimal_amount}"
                    )
                    log_error(error_msg)
                    raise Exception("Bounty not paid to recipient")

                # Payment successful: Update status, amount, and save the BountySolution
                bounty_solution.status = BountySolution.Status.AWARDED
                bounty_solution.awarded_amount = decimal_amount
                bounty_solution.save(
                    update_fields=[
                        "status",
                        "awarded_amount",
                        "updated_date",
                    ]  # Wrapped list
                )
                processed_solutions.append(bounty_solution)

            # Mark remaining SUBMITTED solutions (not in this batch) as REJECTED
            # Using exclude ensures we don't reject solutions just awarded
            submitted_solutions = bounty.solutions.filter(
                status=BountySolution.Status.SUBMITTED
            )
            solutions_to_reject = submitted_solutions.exclude(
                id__in=[s.id for s in processed_solutions]
            )
            solutions_to_reject.update(status=BountySolution.Status.REJECTED)

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

            # Build response using the successfully processed solutions
            awarded_solutions = []
            for solution in processed_solutions:
                first_name = solution.created_by.first_name
                last_name = solution.created_by.last_name
                creator_name = f"{first_name} {last_name}".strip()
                awarded_solutions.append(
                    {
                        "id": solution.id,
                        "content_type": solution.content_type.model,
                        "object_id": solution.object_id,
                        "awarded_amount": str(solution.awarded_amount),
                        "created_by_id": solution.created_by.id,
                        "status": solution.status,
                        "created_by_name": creator_name,
                    }
                )

            response_data = {
                "id": bounty.id,
                "amount": str(bounty.amount),
                "status": bounty.status,
                "created_date": bounty.created_date.isoformat(),
                "expiration_date": (
                    bounty.expiration_date.isoformat()
                    if bounty.expiration_date
                    else None
                ),
                "awarded_solutions": awarded_solutions,
                "message": "Bounty successfully closed and solutions awarded",
            }

            return Response(response_data, status=200)

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

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)

        bounty_types = self.request.query_params.getlist("bounty_type")
        hub_ids = self.request.query_params.getlist("hub_ids")
        only_parent_bounties = (
            self.request.query_params.get("only_parent_bounties") == "true"
        )

        # Build filters
        applied_filters = Q()

        # Only return parent bounties.
        # Child bounty amounts are included in the parent bounty amount
        if only_parent_bounties:
            applied_filters &= Q(parent__isnull=True)

        # Only return bounties within specific hubs
        if hub_ids:
            applied_filters &= Q(unified_document__hubs__id__in=hub_ids)

        # ResearchHub foundation only filter
        if "RESEARCHHUB" in bounty_types:
            researchhub_official_user_accounts = User.objects.filter(
                is_official_account=True
            )
            applied_filters &= Q(created_by__in=researchhub_official_user_accounts)

        # Handle review, answer, and other filters
        review_or_answer_filter = Q()
        if Bounty.Type.REVIEW in bounty_types:
            review_or_answer_filter |= Q(bounty_type=Bounty.Type.REVIEW)
        if Bounty.Type.ANSWER in bounty_types:
            review_or_answer_filter |= Q(bounty_type=Bounty.Type.ANSWER)
        if Bounty.Type.OTHER in bounty_types:
            review_or_answer_filter |= Q(bounty_type=Bounty.Type.OTHER)

        # Only show bounties that have not yet expired.
        # We have a periodic celery task to update expiration of bounties
        # that have expired however, it only runs a few times a day so for
        # a brief period, a situation could arise where a bounty is considered
        # OPEN but has actually expired.
        now = timezone.now()
        applied_filters &= Q(expiration_date__gt=now)

        # Combine the filters
        if review_or_answer_filter:
            applied_filters &= review_or_answer_filter

        # Apply the combined filter
        return queryset.filter(applied_filters)

    def list(self, request, *args, **kwargs):
        sort = self.request.query_params.get("sort", "-created_date")

        # If sort is personalized but user is logged out, default to created_date
        if sort == "personalized" and not request.user.is_authenticated:
            sort = "-created_date"

        if sort == "personalized":
            bounties = Bounty.find_bounties_for_user(
                user=request.user,
                include_unrelated=True,
            )

            queryset = Bounty.objects.filter(id__in=[b.id for b in bounties])
            queryset = self.filter_queryset(queryset)
        else:
            queryset = self.filter_queryset(self.get_queryset())

            # Sorting by amount requires calculating total including child bounties
            if sort == "-total_amount":
                # Subquery to calculate the sum of children amounts
                children_sum = (
                    Bounty.objects.filter(parent=OuterRef("pk"))
                    .values("parent")
                    .annotate(
                        sum=Coalesce(
                            Sum("amount"),
                            Value(
                                0,
                                output_field=DecimalField(
                                    max_digits=19, decimal_places=10
                                ),
                            ),
                        )
                    )
                    .values("sum")
                )

                # Annotate queryset with total_amount for all cases
                queryset = queryset.annotate(
                    total_amount=F("amount")
                    + Coalesce(
                        Subquery(children_sum),
                        Value(
                            0,
                            output_field=DecimalField(max_digits=19, decimal_places=10),
                        ),
                    )
                )

            # Apply sorting
            queryset = queryset.order_by(sort)

        page = self.paginate_queryset(queryset)
        context = self._get_retrieve_context()
        serializer = DynamicBountySerializer(
            page,
            many=True,
            context=context,
            _include_fields=(
                "created_by",
                "created_date",
                "content_type",
                "id",
                "item",
                "expiration_date",
                "status",
                "bounty_type",
                "hubs",
                "total_amount",
                "unified_document",
                "user_vote",
                "metrics",
            ),
        )

        return self.get_paginated_response(serializer.data)

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
