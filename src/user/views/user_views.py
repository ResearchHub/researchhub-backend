from datetime import datetime

from allauth.account.models import EmailAddress
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from purchase.related_models.grant_model import Grant
from reputation.serializers import (
    DynamicBountySerializer,
)
from reputation.views import BountyViewSet
from user.earning_overview_serializer import EarningOverviewSerializer
from user.filters import UserFilter
from user.models import Author, Major, University, User
from user.permissions import (
    Censor,
    DeleteUserPermission,
    IsModerator,
    RequestorIsOwnUser,
    UserIsEditor,
)
from user.serializers import (
    MajorSerializer,
    UniversitySerializer,
    UserEditableSerializer,
    UserSerializer,
)
from user.services.earning_overview_service import EarningOverviewService
from user.tasks import handle_spam_user_task, reinstate_user_task
from user.views.follow_view_mixins import FollowViewActionMixin


class UserViewSet(FollowViewActionMixin, viewsets.ModelViewSet):
    queryset = (
        User.objects.select_related("userverification")
        .annotate(
            is_funder=Exists(
                Grant.objects.filter(
                    created_by=OuterRef("pk"),
                    status__in=[Grant.OPEN, Grant.COMPLETED],
                    unified_document__is_removed=False,
                )
            ),
        )
        .filter(is_suspended=False)
    )
    serializer_class = UserEditableSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, DeleteUserPermission]
    filter_backends = (DjangoFilterBackend,)
    filterset_class = UserFilter

    def get_serializer_class(self):
        if self.request.GET.get("referral_code") or self.request.GET.get("invited_by"):
            return UserSerializer
        else:
            return self.serializer_class

    def get_serializer_context(self):
        return {"get_balance": True, "user": self.request.user}

    def get_queryset(self):
        # TODO: Remove this override
        user = self.request.user
        qs = self.queryset
        author_profile = self.request.query_params.get("author_profile")

        # Allow access to all users for follow-related actions
        if self.action in ["follow", "unfollow", "is_following"]:
            return qs.filter(is_suspended=False)

        if self.request.GET.get("referral_code") or self.request.GET.get("invited_by"):
            return qs
        elif author_profile:
            return User.objects.filter(author_profile=author_profile)
        elif user.is_staff:
            return qs
        elif user.is_authenticated:
            return qs.filter(id=user.id)
        else:
            return User.objects.none()

    @action(detail=False, methods=["POST"], permission_classes=[AllowAny])
    def check_account(self, request):
        user = User.objects.filter(email=request.data["email"]).first()
        if user:
            # Filtering by provider == google because we only have google login
            # If we ever add a second login, we need to update the provider to include
            # those social accounts
            # The case we're guarding against here is ORCID
            social_account = user.socialaccount_set.filter(provider="google").first()
            if social_account:
                return Response(
                    # Social login such as Google do not require email verification
                    {
                        "exists": True,
                        "auth": social_account.provider,
                        "is_verified": True,
                    },
                    status=200,
                )
            else:
                is_verified = False
                email_obj = EmailAddress.objects.filter(user_id=user.id).first()
                if email_obj:
                    is_verified = email_obj.verified

                return Response(
                    {"exists": True, "auth": "email", "is_verified": is_verified},
                    status=200,
                )

        return Response({"exists": False}, status=200)

    @action(detail=False, methods=["POST"], permission_classes=[IsAuthenticated])
    def update_balance_history_clicked(self, request):
        user = request.user
        now = datetime.now()
        user.clicked_on_balance_date = now
        user.save(update_fields=["clicked_on_balance_date"])
        return Response({"data": "ok"}, status=200)

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[IsAuthenticated, Censor],
    )
    def censor(self, request, pk=None):
        author_id = request.data.get("authorId")
        user_to_censor = User.objects.get(author_profile__id=author_id)
        user_to_censor.set_probable_spammer()
        user_to_censor.set_suspended()
        user_to_censor.is_active = False
        user_to_censor.save()
        handle_spam_user_task(user_to_censor.id, request.user)

        return Response({"message": "User is Censored"}, status=200)

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[UserIsEditor | IsModerator],
    )
    def mark_probable_spammer(self, request, pk=None):
        author_id = request.data.get("authorId")

        if not author_id:
            return Response(
                {"message": "authorId is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_to_flag = User.objects.get(author_profile__id=author_id)
        except User.DoesNotExist:
            return Response(
                {"message": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )

        user_to_flag.set_probable_spammer()

        return Response(
            {"message": "User flagged as probable spammer"}, status=status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=["POST"],
        permission_classes=[RequestorIsOwnUser],
    )
    def set_should_display_rsc_balance(self, request, pk=None):
        try:
            user = User.objects.get(id=request.user.id)
            target_value = request.data.get("should_display_rsc_balance_home")
            user.should_display_rsc_balance_home = target_value
            user.save()
            return Response(
                {
                    "user_id": request.user.id,
                    "should_display_rsc_balance_home": target_value,
                }
            )
        except Exception as exception:
            return Response(
                f"Failed to update user: {exception}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["GET"], permission_classes=[AllowAny])
    def bounties(self, request, pk=None):
        user = self.get_object()
        bounties = user.bounties.all().order_by("-created_date")
        page = self.paginate_queryset(bounties)
        bounty_view = BountyViewSet()
        context = bounty_view._get_retrieve_context()
        serializer = DynamicBountySerializer(
            page,
            _include_fields=[
                "amount",
                "content_type",
                "created_date",
                "created_by",
                "expiration_date",
                "id",
                "status",
            ],
            context=context,
            many=True,
        )
        response = self.get_paginated_response(serializer.data)
        return response

    @action(
        detail=False,
        methods=["PATCH"],
    )
    def has_seen_first_coin_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_first_coin_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=["PATCH"],
    )
    def has_seen_orcid_connect_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_orcid_connect_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=["PATCH"],
    )
    def set_staking_opted_in(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        is_opted_in = request.data.get("is_staking_opted_in", False)
        was_opted_in = user.is_staking_opted_in
        user.is_staking_opted_in = is_opted_in
        if is_opted_in and not was_opted_in:
            user.staking_opted_in_date = timezone.now()
        elif not is_opted_in:
            user.staking_opted_in_date = None
        user.save(update_fields=["is_staking_opted_in", "staking_opted_in_date"])
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[IsAuthenticated, Censor],
    )
    def reinstate(self, request):
        author_id = request.data["author_id"]
        user = Author.objects.get(id=author_id).user
        user.is_active = True
        user.is_suspended = False
        user.probable_spammer = False
        user.save()
        reinstate_user_task(user.id)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def earning_overview(self, request, *args, **kwargs):
        """Return earning overview metrics for the authenticated user."""
        user_id = request.query_params.get("user_id")
        if user_id and request.user.moderator:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({"error": "User not found"}, status=404)
        else:
            user = request.user
        data = EarningOverviewService().get_earning_overview(user)
        serializer = EarningOverviewSerializer(data)
        return Response(serializer.data)


class UniversityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = University.objects.all()
    serializer_class = UniversitySerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ("name", "city", "state", "country")
    permission_classes = [AllowAny]

    @method_decorator(cache_page(60 * 60 * 6))
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @method_decorator(cache_page(60 * 60 * 6))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class MajorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Major.objects.all()
    serializer_class = MajorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ("major", "major_category")
    permission_classes = [AllowAny]
