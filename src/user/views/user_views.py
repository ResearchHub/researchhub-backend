import hmac
from datetime import datetime, timedelta
from hashlib import sha1

from allauth.account.models import EmailAddress
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from paper.models import Paper
from paper.serializers import DynamicPaperSerializer
from paper.utils import PAPER_SCORE_Q_ANNOTATION
from reputation.models import Bounty, Distribution
from reputation.serializers import (
    DynamicBountySerializer,
    DynamicBountySolutionSerializer,
)
from reputation.views import BountyViewSet
from researchhub.settings import (
    EMAIL_WHITELIST,
    SIFT_MODERATION_WHITELIST,
    SIFT_WEBHOOK_SECRET_KEY,
)
from user.filters import UserFilter
from user.models import Author, Major, University, User
from user.permissions import Censor, DeleteUserPermission, RequestorIsOwnUser
from user.serializers import (
    AuthorSerializer,
    DynamicUserSerializer,
    MajorSerializer,
    UniversitySerializer,
    UserActions,
    UserEditableSerializer,
    UserSerializer,
)
from user.tasks import handle_spam_user_task, reinstate_user_task
from user.utils import calculate_show_referral
from user.views.follow_view_mixins import FollowViewActionMixin
from utils.http import POST, RequestMethods
from utils.sentry import log_info


class UserViewSet(FollowViewActionMixin, viewsets.ModelViewSet):
    queryset = User.objects.filter(is_suspended=False)
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
        return {"get_subscribed": True, "get_balance": True, "user": self.request.user}

    def destroy(self, request, pk=None):
        with transaction.atomic():
            # Manually retrieving user obj instead of using get_object
            # because this view is legacy and does not support it
            user_to_be_deleted = User.objects.get(id=pk)
            if not DeleteUserPermission().has_object_permission(
                request, self, user_to_be_deleted
            ):
                return Response(status=403)
            author_profile = user_to_be_deleted.author_profile

            # Close any open bounties
            bounties = user_to_be_deleted.bounties.filter(
                status=Bounty.OPEN, parent__isnull=True
            )
            for bounty in bounties.iterator():
                bounty.close(Bounty.EXPIRED)

            user_to_be_deleted.delete()
            author_profile.delete()
            return Response(status=204)

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
            # If we ever add a second login, we need to update the provider to include those social accounts
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

    @action(detail=False, methods=["GET"], permission_classes=[IsAuthenticated])
    def get_referral_reputation(self, request):
        show_referral = calculate_show_referral(request.user)
        return Response({"show_referral": show_referral})

    @action(detail=False, methods=[POST], permission_classes=[IsAuthenticated, Censor])
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
        methods=[RequestMethods.GET],
    )
    def referral_rsc(self, request):
        """
        Gets the amount of RSC earned from referrals
        """

        distributions = (
            Distribution.objects.filter(
                proof_item_content_type=ContentType.objects.get_for_model(User),
                proof_item_object_id=request.user.id,
            )
            .exclude(recipient=request.user.id)
            .aggregate(rsc_earned=Sum("amount"))
        )

        amount = distributions.get("rsc_earned") or 0

        return Response({"amount": amount})

    @action(
        detail=True,
        methods=[RequestMethods.POST],
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

    @method_decorator(cache_page(60 * 60 * 6))
    @action(
        detail=False,
        methods=[RequestMethods.GET],
    )
    def leaderboard(self, request):
        """
        Leaderboard serves both Papers and Users
        """
        hub_id = request.GET.get("hub_id")
        if hub_id:
            hub_id = int(hub_id)

        leaderboard_type = request.GET.get("type", "users")
        """
        createdByOptions can be values:
        1. created_date
        2. published_date
        """
        created_by_options = request.GET.get("dateOption", "created_date")

        """
        Timeframe can be values:
        1. all_time
        2. today
        3. past_week
        4. past_month
        5. past_year
        """
        timeframe = request.GET.get("timeframe", "all_time")

        context = {"request": request}
        serializer_kwargs = {}
        time_filter = {}
        if leaderboard_type == "papers":
            if created_by_options == "created_date":
                keyword = "created_date__gte"
            else:
                keyword = "paper_publish_date__gte"
        elif leaderboard_type == "users":
            keyword = "reputation_records__created_date__gte"
        else:
            keyword = "created_date__gte"

        if timeframe == "today":
            time_filter = {keyword: timezone.now().date()}
        elif timeframe == "past_week":
            time_filter = {keyword: timezone.now().date() - timedelta(days=7)}
        elif timeframe == "past_month":
            time_filter = {keyword: timezone.now().date() - timedelta(days=30)}
        elif timeframe == "past_year":
            time_filter = {keyword: timezone.now().date() - timedelta(days=365)}
        elif timeframe == "all_time":
            time_filter = {keyword: datetime(year=2019, month=1, day=1)}

        items = []
        serializerClass = None
        if leaderboard_type == "papers":
            serializerClass = DynamicPaperSerializer
            if hub_id and hub_id != 0:
                items = (
                    Paper.objects.exclude(
                        is_public=False,
                    )
                    .annotate(paper_score=PAPER_SCORE_Q_ANNOTATION)
                    .filter(**time_filter, hubs__in=[hub_id], is_removed=False)
                    .order_by("-paper_score")
                )
            else:
                items = (
                    Paper.objects.exclude(is_public=False)
                    .annotate(paper_score=PAPER_SCORE_Q_ANNOTATION)
                    .filter(**time_filter, is_removed=False)
                    .order_by("-paper_score")
                )
            serializer_kwargs = {
                "_include_fields": [
                    "id",
                    "abstract",
                    "boost_amount",
                    "discussion_count",
                    "file",
                    "hubs",
                    "paper_title",
                    "score",
                    "title",
                    "slug",
                    "uploaded_by",
                    "uploaded_date",
                ]
            }
        elif leaderboard_type == "users":
            serializerClass = UserSerializer
            items = User.objects.filter(
                is_active=True,
                is_suspended=False,
                probable_spammer=False,
            )

            if hub_id != 0 and hub_id:
                items = items.annotate(
                    hub_rep=Coalesce(
                        Sum(
                            "reputation_records__reputation_amount",
                            filter=Q(
                                **time_filter,
                                reputation_records__hubs__in=[hub_id],
                            )
                            & ~Q(
                                reputation_records__distribution_type__in=[
                                    "REFERRAL",
                                    "PURCHASE",
                                    "REWARD",
                                    "EDITOR_COMPENSATION",
                                    "EDITOR_PAYOUT",
                                    "MOD_PAYOUT",
                                    "CREATE_BULLET_POINT",
                                    "CREATE_SUMMARY",
                                    "SUMMARY_UPVOTED",
                                    "BULLET_POINT_UPVOTED",
                                    "CREATE_FIRST_SUMMARY",
                                    "REFERRAL_APPROVED",
                                    "BOUNTY_DAO_FEE",
                                ]
                            ),
                        ),
                        0,
                    )
                ).order_by(F("hub_rep").desc(nulls_last=True), "-reputation")
            else:
                if timeframe == "all_time":
                    items = items.order_by("-reputation")
                else:
                    items = items.annotate(
                        time_rep=Coalesce(
                            Sum(
                                "reputation_records__reputation_amount",
                                filter=Q(
                                    **time_filter,
                                )
                                & ~Q(
                                    reputation_records__distribution_type__in=[
                                        "REFERRAL",
                                        "PURCHASE",
                                        "REWARD",
                                        "EDITOR_COMPENSATION",
                                        "EDITOR_PAYOUT",
                                        "MOD_PAYOUT",
                                        "CREATE_BULLET_POINT",
                                        "CREATE_SUMMARY",
                                        "SUMMARY_UPVOTED",
                                        "BULLET_POINT_UPVOTED",
                                        "CREATE_FIRST_SUMMARY",
                                        "REFERRAL_APPROVED",
                                    ]
                                ),
                            ),
                            0,
                        )
                    ).order_by(F("time_rep").desc(nulls_last=True), "-reputation")
        elif leaderboard_type == "authors":
            serializerClass = AuthorSerializer
            items = Author.objects.filter(user__is_suspended=False).order_by(
                "-author_score"
            )

        page = self.paginate_queryset(items)
        serializer = serializerClass(
            page, many=True, context=context, **serializer_kwargs
        )

        return self.get_paginated_response(serializer.data)

    @action(
        detail=True, methods=[RequestMethods.GET], permission_classes=[IsAuthenticated]
    )
    def actions(self, request, pk=None):
        user_actions = UserActions(user=request.user)
        page = self.paginate_queryset(user_actions.serialized)
        return self.get_paginated_response(page)

    @action(detail=True, methods=[RequestMethods.GET], permission_classes=[AllowAny])
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

    @action(detail=True, methods=[RequestMethods.GET], permission_classes=[AllowAny])
    def awarded_bounties(self, request, pk=None):
        user = self.get_object()
        solutions = user.solutions.all().order_by("-created_date")
        page = self.paginate_queryset(solutions)
        context = {
            "rep_dbss_get_bounty": {
                "_include_fields": ("content_type", "item", "solutions")
            },
            "rep_dbs_get_solutions": {
                "_include_fields": (
                    "content_type",
                    "item",
                )
            },
            "rep_dbs_get_item": {
                "_include_fields": (
                    "document_type",
                    "documents",
                    "text",
                )
            },
            "rep_dbss_get_item": {
                "_include_fields": (
                    "id",
                    "text",
                    "discussion_post_type",
                )
            },
            "dis_dts_get_unified_document": {"_include_fields": ("document_type",)},
            "dis_dcs_get_unified_document": {"_include_fields": ("document_type",)},
            "dis_drs_get_unified_document": {"_include_fields": ("document_type",)},
            "doc_duds_get_documents": {
                "_include_fields": (
                    "id",
                    "title",
                    "post_title",
                    "slug",
                    "renderable_text",
                )
            },
        }
        serializer = DynamicBountySolutionSerializer(
            page,
            _include_fields=[
                "bounty",
                # "content_type",
                # "item",
            ],
            context=context,
            many=True,
        )
        response = self.get_paginated_response(serializer.data)
        return response

    @action(
        detail=False,
        methods=[RequestMethods.PATCH],
    )
    def has_seen_first_coin_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_first_coin_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.PATCH],
    )
    def has_seen_orcid_connect_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_orcid_connect_modal(True)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.PATCH],
    )
    def has_completed_onboarding(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.has_completed_onboarding = True
        user.save()
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    @action(
        detail=False,
        methods=[RequestMethods.POST],
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

    @action(
        detail=False,
        methods=[RequestMethods.POST],
        permission_classes=[AllowAny],
    )
    def sift_check_user_content(self, request):
        # https://sift.com/developers/docs/python/decisions-api/decision-webhooks/authentication

        # Let's check whether this webhook actually came from Sift!
        # First let's grab the signature from the postback's headers
        postback_signature = request.headers.get("X-Sift-Science-Signature")

        # Next, let's try to assemble the signature on our side to verify
        key = SIFT_WEBHOOK_SECRET_KEY.encode("utf-8")
        postback_body = request.body

        h = hmac.new(key, postback_body, sha1)
        verification_signature = "sha1={}".format(h.hexdigest())

        if verification_signature == postback_signature:
            # Custom logic here
            decision_id = request.data["decision"]["id"]
            user_id = request.data["entity"]["id"]
            user = User.objects.get(id=user_id)

            if (
                not user.moderator or user.email not in EMAIL_WHITELIST
            ) and user.id not in SIFT_MODERATION_WHITELIST:
                if "mark_as_probable_spammer_content_abuse" in decision_id:
                    log_info(
                        f"Possible Spammer - {user.id}: {user.first_name} {user.last_name} - {decision_id}"
                    )
                    user.set_probable_spammer()
                elif "suspend_user_content_abuse" in decision_id:
                    log_info(
                        f"Suspending User - {user.id}: {user.first_name} {user.last_name} - {decision_id}"
                    )
                    user.set_suspended(is_manual=False)
                    user.is_active = False
                    user.save()

            serialized = UserSerializer(user)
            return Response(serialized.data, status=200)
        else:
            raise Exception("Sift verification signature mismatch")


@api_view([RequestMethods.GET])
@permission_classes([AllowAny])
def get_user_popover(request, user_id=None):
    user = get_object_or_404(User, pk=user_id)
    user = User.objects.get(id=user_id)
    context = {
        "usr_dus_get_author_profile": {
            "_include_fields": (
                "id",
                "first_name",
                "last_name",
                "university",
                "facebook",
                "linkedin",
                "twitter",
                "google_scholar",
                "description",
                "education",
                "headline",
                "profile_image",
            )
        },
        "usr_dus_get_editor_of": {"_include_fields": ("source",)},
        "rag_dps_get_source": {"_include_fields": ("id", "name", "slug")},
    }
    serializer = DynamicUserSerializer(
        user,
        context=context,
        _include_fields=(
            "id",
            "author_profile",
            "editor_of",
            "first_name",
            "last_name",
            "reputation",
            "created_date",
        ),
    )
    return Response(serializer.data, status=200)


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
