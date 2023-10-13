import hmac
from datetime import datetime, timedelta
from hashlib import sha1

from allauth.account.models import EmailAddress
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from requests.exceptions import HTTPError
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from discussion.models import Comment, Reply, Thread
from discussion.serializers import DynamicThreadSerializer
from hypothesis.related_models.hypothesis import Hypothesis
from paper.models import Paper
from paper.serializers import DynamicPaperSerializer
from paper.tasks import pull_openalex_author_works
from paper.utils import PAPER_SCORE_Q_ANNOTATION, get_cache_key
from paper.views import PaperViewSet
from reputation.models import Bounty, BountySolution, Contribution, Distribution
from reputation.serializers import (
    DynamicBountySerializer,
    DynamicBountySolutionSerializer,
    DynamicContributionSerializer,
)
from reputation.views import BountyViewSet
from researchhub.settings import (
    EMAIL_WHITELIST,
    REFERRAL_PROGRAM,
    SIFT_MODERATION_WHITELIST,
    SIFT_WEBHOOK_SECRET_KEY,
)
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.serializers import DynamicPostSerializer
from review.models.review_model import Review
from user.filters import AuthorFilter, UserFilter
from user.models import (
    Author,
    Follow,
    Major,
    University,
    User,
    UserApiToken,
    Verification,
)
from user.permissions import (
    Censor,
    DeleteAuthorPermission,
    DeleteUserPermission,
    HasVerificationPermission,
    RequestorIsOwnUser,
    UpdateAuthor,
)
from user.serializers import (
    AuthorEditableSerializer,
    AuthorSerializer,
    DynamicUserSerializer,
    MajorSerializer,
    UniversitySerializer,
    UserActions,
    UserEditableSerializer,
    UserSerializer,
    VerificationFileSerializer,
    VerificationSerializer,
)
from user.tasks import handle_spam_user_task, reinstate_user_task
from user.utils import calculate_show_referral, reset_latest_acitvity_cache
from utils.http import POST, RequestMethods
from utils.openalex import OpenAlex
from utils.permissions import CreateOrUpdateIfAllowed
from utils.sentry import log_error, log_info
from utils.throttles import THROTTLE_CLASSES


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(is_suspended=False)
    serializer_class = UserEditableSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, DeleteUserPermission]
    filter_backends = (DjangoFilterBackend,)
    filter_class = UserFilter

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

    @action(detail=False, methods=["GET"], permission_classes=[IsAuthenticated])
    def get_referred_users(self, request):
        invited = User.objects.filter(invited_by=request.user).annotate(
            rsc_earned=Sum(
                "reputation_handed_out__amount",
                filter=(
                    Q(
                        reputation_handed_out__distribution_type="REFERRAL_REFERER_EARNINGS"
                    )
                    & Q(reputation_handed_out__recipient_id=request.user)
                ),
            ),
            benefits_expire_on=models.ExpressionWrapper(
                models.F("created_date")
                + timedelta(
                    days=REFERRAL_PROGRAM["ELIGIBLE_TIME_PERIOD_IN_MONTHS"] * 30
                ),
                output_field=models.DateTimeField(),
            ),
        )

        return Response(
            DynamicUserSerializer(
                invited,
                many=True,
                _include_fields=(
                    "created_date",
                    "id",
                    "author_profile",
                    "rsc_earned",
                    "benefits_expire_on",
                ),
            ).data
        )

    def get_queryset(self):
        # TODO: Remove this override
        user = self.request.user
        qs = self.queryset
        author_profile = self.request.query_params.get("author_profile")
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
        handle_spam_user_task(user_to_censor.id)

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
        detail=True, methods=[RequestMethods.POST], permission_classes=[IsAuthenticated]
    )
    def follow(self, request, pk=None):
        data = request.data
        user = self.get_object()
        followee_id = data.get("followee_id")
        followee = Author.objects.get(id=followee_id).user

        try:
            follow = Follow.objects.create(user=user, followee=followee)
        except IntegrityError:
            follow = Follow.objects.get(user=user, followee=followee)
            follow.delete()

        is_following = user.following.filter(followee=followee).exists()
        return Response(is_following, status=200)

    @action(
        detail=True, methods=[RequestMethods.GET], permission_classes=[IsAuthenticated]
    )
    def following(self, request, pk=None):
        user = self.get_object()
        following_ids = user.following.values_list("followee")
        following = self.queryset.filter(id__in=following_ids)
        serializer = UserSerializer(following, many=True)
        data = {user["id"]: user for user in serializer.data}
        return Response(data, status=200)

    @action(
        detail=True, methods=[RequestMethods.GET], permission_classes=[IsAuthenticated]
    )
    def check_follow(self, request, pk=None):
        user = request.user
        followee = Author.objects.get(id=pk).user
        is_following = user.following.filter(followee=followee).exists()
        return Response(is_following, status=200)

    @action(detail=False, methods=[RequestMethods.GET], permission_classes=[AllowAny])
    def following_latest_activity(self, request):
        query_params = request.query_params
        ordering = query_params.get("ordering", "-created_date")
        hub_ids = query_params.get("hub_ids", "")
        page_number = query_params.get("page", 1)

        cache_hit = self._get_latest_activity_cache_hit(request, hub_ids)
        if cache_hit and page_number == 1:
            return Response(cache_hit)

        contributions = self._get_latest_activity_queryset(hub_ids, ordering)

        page = self.paginate_queryset(contributions)
        context = self._get_latest_activity_context()
        serializer = DynamicContributionSerializer(
            page,
            _include_fields=[
                "contribution_type",
                "created_date",
                "id",
                "source",
                "unified_document",
                "user",
            ],
            context=context,
            many=True,
        )
        response = self.get_paginated_response(serializer.data)

        if not cache_hit and page_number == 1:
            reset_latest_acitvity_cache(hub_ids, ordering)
        return response

    def _get_latest_activity_cache_hit(self, request, hub_ids):
        hub_ids_list = hub_ids.split(",")
        if len(hub_ids_list) > 1:
            results = {}
            count = 0
            previous = ""
            next_url = request.build_absolute_uri()
            for hub_id in hub_ids_list:
                cache_key = get_cache_key("contributions", hub_id)
                cache_hit = cache.get(cache_key)
                if not cache_hit:
                    return None

                for hit in cache_hit["results"]:
                    hit_id = hit["id"]
                    if hit_id not in results:
                        results[hit_id] = hit
                count += cache_hit.get("count", 1)

            results = list(results.values())
            results = sorted(
                results, key=lambda contrib: contrib["created_date"], reverse=True
            )[:10]
            next_url = replace_query_param(next_url, "page", 2)

            data = {
                "count": count,
                "next": next_url,
                "previous": previous,
                "results": results,
            }
            return data
        else:
            cache_key = get_cache_key("contributions", hub_ids)
            cache_hit = cache.get(cache_key)
            return cache_hit

    def _get_latest_activity_queryset(self, hub_ids, ordering):
        # following_ids = user.following.values_list('followee')
        contribution_type = [
            Contribution.SUBMITTER,
            Contribution.COMMENTER,
            Contribution.SUPPORTER,
        ]

        rh_comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        comment_content_type = ContentType.objects.get_for_model(Comment)
        reply_content_type = ContentType.objects.get_for_model(Reply)
        removed_threads = Thread.objects.filter(is_removed=True)
        removed_comments = Comment.objects.filter(is_removed=True)
        removed_replies = Reply.objects.filter(is_removed=True)

        contributions = (
            Contribution.objects.select_related(
                "content_type",
                "user",
                "user__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
            )
            .filter(
                unified_document__is_removed=False,
                contribution_type__in=contribution_type,
            )
            .exclude(
                (
                    (
                        Q(content_type=rh_comment_content_type)
                        & Q(object_id__in=removed_threads)
                    )
                    | (
                        Q(content_type=comment_content_type)
                        & Q(object_id__in=removed_comments)
                    )
                    | (
                        Q(content_type=reply_content_type)
                        & Q(object_id__in=removed_replies)
                    )
                )
            )
        )

        if hub_ids:
            hub_ids = hub_ids.split(",")
            hub_ids = [int(i) for i in hub_ids]
            contributions = contributions.filter(
                unified_document__hubs__in=hub_ids
            ).order_by(ordering)
        else:
            contributions = contributions.order_by(ordering)
        contributions = contributions.distinct()
        return contributions

    def _get_latest_activity_context(self):
        context = {
            "doc_duds_get_documents": {
                "_include_fields": [
                    "created_date",
                    "id",
                    "slug",
                    "title",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                ]
            },
            "rep_dcs_get_source": {
                "_include_fields": [
                    "abstract",
                    "amount",
                    "id",
                    "paper_title",
                    "slug",
                    "text",
                    "title",
                ]
            },
            "rep_dcs_get_unified_document": {
                "_include_fields": [
                    "created_date",
                    "documents",
                    "document_type",
                    "hubs",
                ]
            },
            "rep_dcs_get_user": {
                "_include_fields": [
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
        }
        return context

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
    def has_seen_stripe_modal(self, request):
        user = request.user
        user = User.objects.get(pk=user.id)
        user.set_has_seen_stripe_modal(True)
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
        user.is_suspended = False
        user.probable_spammer = False
        user.save()
        reinstate_user_task(user.id)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=200)

    # TODO: Permissions
    @action(
        detail=False,
        methods=[RequestMethods.POST],
        permission_classes=[HasVerificationPermission],
    )
    def verify_user(self, request):
        data = request.data
        openalex_id = data.get("openalex_id", None)
        user = request.user
        author_profile = user.author_profile

        if openalex_id is None:
            return Response(status=400)

        try:
            user.is_verified = True
            author_profile.openalex_id = openalex_id
            author_profile.is_verified = True
            author_profile.save(update_fields=["openalex_id", "is_verified"])
            user.save(update_fields=["is_verified"])
            pull_openalex_author_works.apply_async(
                (user.id, openalex_id), countdown=3, priority=6
            )
        except Exception as e:
            log_error(e)
            raise e
        finally:
            user.api_keys.filter(
                name=UserApiToken.TEMPORARY_VERIFICATION_TOKEN
            ).delete()

        return Response(status=200)

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
            serialized = UserSerializer(user)
            return Response(serialized.data, status=200)
        else:
            raise Exception("Sift verification signature mismatch")


@api_view([RequestMethods.GET])
@permission_classes([AllowAny])
def get_user_popover(request, pk=None):
    user = get_object_or_404(User, pk=pk)
    user = User.objects.get(id=pk)
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


class VerificationViewSet(viewsets.ModelViewSet):
    queryset = Verification.objects.all()
    serializer_class = VerificationSerializer
    # TODO: Permissions
    permission_classes = [AllowAny]
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_fields = ("status",)
    ordering_fields = ("created_date",)
    throttle_classes = THROTTLE_CLASSES

    def create(self, request, *args, **kwargs):
        user = request.user
        with transaction.atomic():
            try:
                files = request.data.getlist("file[]")
                res = super().create(request, *args, **kwargs)
                for file in files:
                    data = {"verification": res.data["id"], "file": file}
                    serializer = VerificationFileSerializer(data=data)
                    serializer.is_valid(raise_exception=True)
                    serializer.save()
            except Exception as e:
                user.api_keys.filter(
                    name=UserApiToken.TEMPORARY_VERIFICATION_TOKEN
                ).delete()
                raise e
            return res

    @action(
        detail=False,
        methods=["post"],
    )
    def bulk_upload(self, request):
        return Response({"message": "Deprecated"})

    @action(
        detail=False, methods=["post"], permission_classes=[HasVerificationPermission]
    )
    def get_openalex_author_profiles(self, request):
        data = request.data
        user = request.user

        UserApiToken.objects.get(name=UserApiToken.TEMPORARY_VERIFICATION_TOKEN)
        request_type = data.get("request_type")
        oa = OpenAlex()

        if request_type == "ORCID":
            author_profile = user.author_profile
            orcid_id = author_profile.orcid_id
            try:
                author = oa.get_author_via_orcid(orcid_id)
                res = oa._get_works_from_api_url(author)
            except HTTPError as e:
                log_error(e)
                return Response(
                    {"error": "No profile found with associated ID"}, status=404
                )
        elif request_type == "NAME":
            manual_name_input = data.get("name", None)
            if manual_name_input:
                authors = oa.search_authors_via_name(manual_name_input)
            else:
                name = f"{user.first_name} {user.last_name}"
                authors = oa.search_authors_via_name(name)
            res = oa._get_works_from_api_url(authors)
        else:
            return Response(status=400)

        return Response(res, status=200)


class AuthorViewSet(viewsets.ModelViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    filter_class = AuthorFilter
    search_fields = ("first_name", "last_name")
    permission_classes = [
        (IsAuthenticatedOrReadOnly & UpdateAuthor & CreateOrUpdateIfAllowed)
        | DeleteAuthorPermission
    ]
    throttle_classes = THROTTLE_CLASSES

    def create(self, request, *args, **kwargs):
        """Override to use an editable serializer."""
        serializer = AuthorEditableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request, *args, **kwargs):
        """Override to use an editable serializer."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = AuthorEditableSerializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get"],
    )
    def get_authored_papers(self, request, pk=None):
        author = self.get_object()
        prefetch_lookups = PaperViewSet.prefetch_lookups(self)
        authored_papers = (
            author.authored_papers.filter(is_removed=False)
            .prefetch_related(
                *prefetch_lookups,
            )
            .annotate(paper_score=PAPER_SCORE_Q_ANNOTATION)
            .order_by("-paper_score")
        )
        context = self._get_authored_papers_context()
        page = self.paginate_queryset(authored_papers)
        serializer = DynamicPaperSerializer(
            page,
            _include_fields=[
                "id",
                "abstract",
                "authors",
                "boost_amount",
                "file",
                "first_preview",
                "hubs",
                "paper_title",
                "score",
                "title",
                "uploaded_by",
                "uploaded_date",
                "url",
                "paper_publish_date",
                "slug",
                "created_date",
            ],
            many=True,
            context=context,
        )
        response = self.get_paginated_response(serializer.data)
        return response

    def _get_authored_papers_context(self):
        context = {
            "pap_dps_get_authors": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_first_preview": {
                "_include_fields": [
                    "file",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": (
                    "id",
                    "slug",
                    "name",
                )
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "hub_image",
                ]
            },
        }
        return context

    def _get_contribution_context(self, filter_by_user_id):
        context = {
            "request": self.request,
            "_config": {
                "filter_by_user_id": filter_by_user_id,
            },
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_duds_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_review": {
                "_include_fields": [
                    "id",
                    "score",
                ]
            },
            "dis_dcs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "dis_drs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "pap_dps_get_user_vote": {
                "_include_fields": [
                    "id",
                    "created_by",
                    "created_date",
                    "vote_type",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "pap_dpvs_paper": {"_exclude_fields": "__all__"},
            "doc_dps_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_drs_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dcs_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dts_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dts_get_comments": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "dis_dcs_get_replies": {
                "_include_fields": [
                    "created_by",
                    "created_location",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "score",
                    "text",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "created_date",
                    "updated_date",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "promoted",
                    "abstract",
                    "aggregate_citation_consensus",
                    "created_by",
                    "created_date",
                    "hot_score",
                    "hubs",
                    "id",
                    "discussion_count",
                    "paper_title",
                    "preview_img",
                    "renderable_text",
                    "score",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                    "user_vote",
                ]
            },
            "doc_duds_get_bounties": {"_include_fields": ["id"]},
            "rep_dcs_get_author": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "rep_dcs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "hubs",
                ]
            },
            "rep_dcs_get_source": {
                "_include_fields": [
                    "amount",
                    "citation",
                    "comment_count",
                    "comment_content_json",
                    "children",
                    "content_type",
                    "created_by",
                    "created_date",
                    "created_location",
                    "discussion_type",
                    "document_meta",
                    "external_metadata",
                    "hypothesis",
                    "id",
                    "is_public",
                    "is_removed",
                    "paper_slug",
                    "paper_title",
                    "paper",
                    "plain_text",
                    "post_slug",
                    "post",
                    "promoted",
                    "replies",
                    "review",
                    "score",
                    "slug",
                    "source",
                    "text",
                    "title",
                    "user_flag",
                    "user_vote",
                ]
            },
            "rep_dbs_get_item": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "thread_id",
                    "paper",
                    "post",
                    "awarded_bounty_amount",
                    "unified_document",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "rep_dbss_get_item": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "awarded_bounty_amount",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "rep_dbs_get_created_by": {"_include_fields": ["author_profile", "id"]},
            "dis_dts_get_bounties": {
                "_include_fields": [
                    "amount",
                    "created_by",
                ]
            },
            "dis_dts_get_paper": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "dis_dts_get_post": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "hyp_dhs_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "hyp_dhs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "rhc_dcs_get_created_by": {
                "_include_fields": [
                    "first_name",
                    "last_name",
                    "author_profile",
                ]
            },
            "rhc_dcs_get_children": {
                "_exclude_fields": [
                    "thread",
                    "comment_content_src",
                    "promoted",
                    "user_endorsement",
                    "user_flag",
                    "purchases",
                ]
            },
            "rhc_dcs_get_purchases": {
                "_include_fields": [
                    "amount",
                    "user",
                ]
            },
            "rev_drs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "pch_dps_get_user": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=["get"],
    )
    def contributions(self, request, pk=None):
        author = self.get_object()

        query_params = request.query_params
        ordering = query_params.get("ordering", "-created_date")
        asset_type = query_params.get("type", "overview")
        contributions = self._get_author_contribution_queryset(
            author.id, ordering, asset_type
        )

        page = self.paginate_queryset(contributions)
        context = self._get_contribution_context(author.user_id)
        serializer = DynamicContributionSerializer(
            page,
            _include_fields=[
                "contribution_type",
                "created_date",
                "id",
                "source",
                "created_by",
                "unified_document",
                "author",
            ],
            context=context,
            many=True,
        )
        data = serializer.data
        response = self.get_paginated_response(data)
        if asset_type == "bounty_offered":
            total_bounty_amount = contributions.aggregate(
                total_amount=Sum("bounty__amount")
            )
            response.data["total_bounty_amount"] = total_bounty_amount.get(
                "total_amount", 0
            )

        return response

    def _get_author_threads_participated(self, author_id):
        author = self.get_object()
        user = author.user

        if user:
            user_threads = RhCommentModel.objects.filter(
                Q(children__created_by=user) | Q(created_by=user)
            )
            return user_threads
        return []

    def _get_author_contribution_queryset(self, author_id, ordering, asset_type):
        author_threads = self._get_author_threads_participated(author_id)
        rh_comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        paper_content_type = ContentType.objects.get_for_model(Paper)
        hypothesis_content_type = ContentType.objects.get_for_model(Hypothesis)
        review_content_type = ContentType.objects.get_for_model(Review)
        bounty_content_type = ContentType.objects.get_for_model(Bounty)
        bounty_solution_content_type = ContentType.objects.get_for_model(BountySolution)

        types = asset_type.split(",")

        query = Q()
        for asset_type in types:
            if asset_type == "overview":
                query |= Q(
                    Q(
                        unified_document__is_removed=False,
                        content_type=rh_comment_content_type,
                        object_id__in=author_threads,
                        contribution_type__in=[
                            Contribution.COMMENTER,
                        ],
                    )
                    | Q(
                        unified_document__is_removed=False,
                        user__author_profile=author_id,
                        content_type_id__in=[
                            hypothesis_content_type,
                            paper_content_type,
                            post_content_type,
                            review_content_type,
                        ],
                        contribution_type__in=[
                            Contribution.SUBMITTER,
                            Contribution.SUPPORTER,
                        ],
                    )
                )
            elif asset_type == "discussion":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=post_content_type,
                    contribution_type__in=[Contribution.SUBMITTER],
                )
            elif asset_type == "hypothesis":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=hypothesis_content_type,
                    contribution_type__in=[Contribution.SUBMITTER],
                )
            elif asset_type == "comment":
                query |= Q(
                    unified_document__is_removed=False,
                    content_type=rh_comment_content_type,
                    object_id__in=author_threads,
                    contribution_type__in=[Contribution.COMMENTER],
                )
            elif asset_type == "paper":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=paper_content_type,
                    contribution_type__in=[Contribution.SUBMITTER],
                )
            elif asset_type == "bounty_offered":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=bounty_content_type,
                    contribution_type__in=[Contribution.BOUNTY_CREATED],
                )
            elif asset_type == "bounty_earned":
                query |= Q(
                    unified_document__is_removed=False,
                    user__author_profile=author_id,
                    content_type_id=bounty_solution_content_type,
                    contribution_type__in=[Contribution.BOUNTY_SOLUTION],
                )
            else:
                raise Exception("Unrecognized asset type")

        qs = (
            Contribution.objects.filter(query)
            .select_related(
                "content_type",
                "user",
                "user__author_profile",
                "unified_document",
            )
            .order_by(ordering)
        )

        return qs

    @action(
        detail=True,
        methods=["get"],
    )
    def get_user_discussions(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            user_discussions = user.thread_set.filter(is_removed=False).order_by("-id")
        else:
            user_discussions = self.queryset.none()

        page = self.paginate_queryset(user_discussions)
        context = self._get_user_discussion_context()
        serializer = DynamicThreadSerializer(
            page,
            _include_fields=[
                "id",
                "comment_count",
                "created_by",
                "created_date",
                "paper",
                "post",
                "score",
                "text",
            ],
            many=True,
            context=context,
        )
        return self.get_paginated_response(serializer.data)

    def _get_user_discussion_context(self):
        context = {
            "dis_dts_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_paper": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "dis_dts_get_post": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
        }
        return context

    @action(
        detail=True,
        methods=["get"],
    )
    def get_user_contributions(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            prefetch_lookups = PaperViewSet.prefetch_lookups(self)
            user_paper_uploads = user.papers.filter(is_removed=False).prefetch_related(
                *prefetch_lookups
            )
        else:
            user_paper_uploads = self.queryset.none()

        context = self._get_user_contributions_context()
        page = self.paginate_queryset(user_paper_uploads)
        serializer = DynamicPaperSerializer(
            page,
            _include_fields=[
                "id",
                "abstract",
                "boost_amount",
                "file",
                "hubs",
                "paper_title",
                "score",
                "title",
                "slug",
                "uploaded_by",
                "uploaded_date",
            ],
            many=True,
            context=context,
        )
        response = self.get_paginated_response(serializer.data)

        return response

    def _get_user_contributions_context(self):
        context = {
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "hub_image",
                ]
            },
        }
        return context

    @action(
        detail=True,
        methods=["get"],
    )
    def get_user_posts(self, request, pk=None):
        author = self.get_object()
        user = author.user

        if user:
            user_posts = user.created_posts.all().prefetch_related(
                "unified_document", "purchases"
            )
        else:
            user_posts = self.queryset.none()

        context = self._get_user_posts_context()
        page = self.paginate_queryset(user_posts)
        serializer = DynamicPostSerializer(
            page,
            _include_fields=[
                "id",
                "created_by",
                "hubs",
                "boost_amount",
                "renderable_text",
                "score",
                "slug",
                "title",
            ],
            many=True,
            context=context,
        )
        response = self.get_paginated_response(serializer.data)
        return response

    def _get_user_posts_context(self):
        context = {
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": ["id", "first_name", "last_name", "profile_image"]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                    "hub_image",
                ]
            },
        }
        return context
