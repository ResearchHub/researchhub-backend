import logging

import dj_rest_auth.registration.serializers as rest_auth_serializers
from django.contrib.contenttypes.models import ContentType
from rest_framework.serializers import (
    CharField,
    IntegerField,
    ModelSerializer,
    PrimaryKeyRelatedField,
    SerializerMethodField,
)

from bullet_point.models import BulletPoint
from bullet_point.models import Vote as BulletVote
from discussion.lib import check_is_discussion_item
from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as GrmVote
from hub.models import Hub
from hub.serializers import DynamicHubSerializer, HubSerializer, SimpleHubSerializer
from hypothesis.models import Hypothesis
from institution.serializers import DynamicInstitutionSerializer
from paper.models import Paper, PaperSubmission
from paper.related_models.authorship_model import Authorship
from purchase.models import Purchase
from reputation.models import Bounty, Contribution, Distribution, Score, Withdrawal
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_access_group.constants import EDITOR
from researchhub_access_group.serializers import DynamicPermissionSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
from summary.models import Summary
from summary.models import Vote as SummaryVote
from user.models import (
    Action,
    Author,
    Major,
    Organization,
    University,
    User,
    UserApiToken,
    UserVerification,
    Verdict,
)
from user.related_models.author_contribution_summary_model import (
    AuthorContributionSummary,
)
from user.related_models.author_institution import AuthorInstitution
from user.related_models.coauthor_model import CoAuthor
from user.related_models.gatekeeper_model import Gatekeeper
from utils import sentry


class UniversitySerializer(ModelSerializer):
    class Meta:
        model = University
        fields = "__all__"


class AuthorSerializer(ModelSerializer):
    added_as_editor_date = SerializerMethodField()
    is_hub_editor_of = SerializerMethodField()
    is_hub_editor = SerializerMethodField()
    num_posts = SerializerMethodField()
    orcid_id = SerializerMethodField()
    reputation = SerializerMethodField()
    reputation_v2 = SerializerMethodField()
    reputation_list = SerializerMethodField()
    sift_link = SerializerMethodField()
    total_score = SerializerMethodField()
    university = UniversitySerializer(required=False)
    wallet = SerializerMethodField()
    suspended_status = SerializerMethodField()
    is_verified_v2 = SerializerMethodField()

    class Meta:
        model = Author
        fields = [field.name for field in Author._meta.fields] + [
            "added_as_editor_date",
            "claimed_by_user_author_id",
            "is_claimed",
            "is_hub_editor_of",
            "is_hub_editor",
            "num_posts",
            "orcid_id",
            "reputation",
            "reputation_v2",
            "reputation_list",
            "suspended_status",
            "sift_link",
            "total_score",
            "university",
            "wallet",
            "is_verified",
            "is_verified_v2",
        ]
        read_only_fields = [
            "added_as_editor_date",
            "claimed_by_user_author_id",
            "is_claimed",
            "is_hub_editor_of",
            "num_posts",
            "merged_with",
            "is_verified",
            "is_verified_v2",
        ]

    def get_reputation(self, obj):
        if obj.user is None:
            return 0
        return obj.user.reputation

    def get_is_verified_v2(self, obj):
        if obj.user is None:
            return False

        user_verification = UserVerification.objects.filter(user=obj.user).last()
        return user_verification.is_verified if user_verification else False

    def get_reputation_v2(self, author):
        score = Score.objects.filter(author=author).order_by("-score").first()

        if score is None:
            return None

        hub = Hub.objects.get(id=score.hub_id)

        return {
            "hub": {
                "id": hub.id,
                "name": hub.name,
                "slug": hub.slug,
            },
            "score": score.score,
            "percentile": score.percentile,
            "bins": [
                [0, 1000],
                [1000, 10000],
                [10000, 100000],
                [100000, 1000000],
            ],  # FIXME: Replace with bins from algo vars table
        }

    def get_reputation_list(self, author):
        scores = Score.objects.filter(author=author, score__gt=0).order_by("-score")
        reputation_list = []
        for score in scores:
            hub = Hub.objects.get(id=score.hub_id)
            reputation_list.append(
                {
                    "hub": {
                        "id": hub.id,
                        "name": hub.name,
                        "slug": hub.slug,
                    },
                    "score": score.score,
                    "percentile": score.percentile,
                    "bins": [
                        [0, 1000],
                        [1000, 10000],
                        [10000, 100000],
                        [100000, 1000000],
                    ],  # FIXME: Replace with bins from algo vars table
                }
            )

        return reputation_list

    def get_orcid_id(self, author):
        return author.orcid_id

    def get_total_score(self, author):
        if author.author_score > 0:
            return author.author_score

    def get_wallet(self, obj):
        from purchase.serializers import WalletSerializer

        if not self.context.get("include_wallet", False):
            return

        try:
            return WalletSerializer(obj.wallet).data
        except Exception:
            pass

    def get_sift_link(self, author):
        user = author.user
        if user:
            user_id = user.id
            sift_link = (
                f"https://console.sift.com/users/{user_id}?abuse_type=content_abuse"
            )
            return sift_link
        return None

    def get_num_posts(self, author):
        user = author.user
        if user:
            return ResearchhubPost.objects.filter(created_by=user).count()
        return 0

    def get_suspended_status(self, author):
        user = author.user

        if user:
            return {
                "probable_spammer": user.probable_spammer,
                "is_suspended": user.is_suspended,
            }
        return {"probable_spammer": False, "is_suspended": False}

    def get_added_as_editor_date(self, author):
        user = author.user
        if user is None:
            return None

        hub_content_type = ContentType.objects.get_for_model(Hub)
        editor_permissions = user.permissions.filter(
            access_type=EDITOR, content_type=hub_content_type
        ).order_by("created_date")

        if editor_permissions.exists():
            editor = editor_permissions.first()
            return editor.created_date

        return None

    def get_is_hub_editor_of(self, author):
        user = author.user
        if user is None:
            return []

        hub_content_type = ContentType.objects.get_for_model(Hub)
        target_permissions = user.permissions.filter(
            access_type=EDITOR, content_type=hub_content_type
        )
        target_hub_ids = []
        for permission in target_permissions:
            target_hub_ids.append(permission.object_id)
        return SimpleHubSerializer(
            Hub.objects.filter(id__in=target_hub_ids), many=True
        ).data

    def get_is_hub_editor(self, author):
        user = author.user
        if user:
            return user.is_hub_editor()


class MajorSerializer(ModelSerializer):
    class Meta:
        model = Major
        fields = "__all__"


class GatekeeperSerializer(ModelSerializer):
    class Meta:
        model = Gatekeeper
        fields = "__all__"
        read_only_fields = [field.name for field in Gatekeeper._meta.fields]


class UserApiTokenSerializer(ModelSerializer):
    class Meta:
        model = UserApiToken
        fields = ["name", "prefix", "revoked"]
        read_only_fields = [field.name for field in UserApiToken._meta.fields]


class DynamicAuthorSerializer(DynamicModelFieldSerializer):
    count = IntegerField(read_only=True)

    class Meta:
        model = Author
        fields = "__all__"


class AuthorEditableSerializer(ModelSerializer):
    university = PrimaryKeyRelatedField(
        queryset=University.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Author
        fields = [field.name for field in Author._meta.fields] + ["university"]
        read_only_fields = [
            "academic_verification",
            "author_score",
            "created_date",
            "claimed",
            "id",
            "merged_with",
            "orcid",
            "orcid_account",
            "user",
        ]


class EditorContributionSerializer(ModelSerializer):
    author_profile = AuthorSerializer(read_only=True)
    comment_count = IntegerField(read_only=True)
    latest_comment_date = SerializerMethodField(read_only=True)
    latest_submission_date = SerializerMethodField(read_only=True)
    submission_count = IntegerField(read_only=True)
    support_count = IntegerField(read_only=True)
    total_contribution_count = IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            "author_profile",
            "comment_count",
            "latest_comment_date",
            "latest_submission_date",
            "id",
            "submission_count",
            "support_count",
            "total_contribution_count",
        ]
        read_only_fields = [
            "author_profile",
            "comment_count",
            "id",
            "submission_count",
            "support_count",
            "total_contribution_count",
        ]

    def get_latest_comment_date(self, user):
        contribution_qs = user.contributions.filter(
            contribution_type=Contribution.COMMENTER,
        )
        target_hub_id = self.context.get("target_hub_id")
        if target_hub_id is not None:
            contribution_qs = contribution_qs.filter(
                unified_document__hubs__in=[target_hub_id]
            )
        try:
            return contribution_qs.latest("created_date").created_date
        except Exception:
            return None

    def get_latest_submission_date(self, user):
        contribution_qs = user.contributions.filter(
            contribution_type=Contribution.SUBMITTER,
        )
        target_hub_id = self.context.get("target_hub_id")
        if target_hub_id is not None:
            contribution_qs = contribution_qs.filter(
                unified_document__hubs__in=[target_hub_id]
            )
        try:
            return contribution_qs.latest("created_date").created_date
        except Exception:
            return None


class UserSerializer(ModelSerializer):
    author_profile = AuthorSerializer(read_only=True)
    balance = SerializerMethodField(read_only=True)
    subscribed = SerializerMethodField(read_only=True)
    hub_rep = SerializerMethodField()
    time_rep = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "author_profile",
            "balance",
            "bookmarks",
            "created_date",
            "has_seen_first_coin_modal",
            "has_seen_orcid_connect_modal",
            "is_suspended",
            "probable_spammer",
            "is_verified",
            "moderator",
            "reputation",
            "subscribed",
            "updated_date",
            "upload_tutorial_complete",
            "hub_rep",
            "time_rep",
            "probable_spammer",
        ]
        read_only_fields = [
            "id",
            "author_profile",
            "bookmarks",
            "created_date",
            "has_seen_first_coin_modal",
            "has_seen_orcid_connect_modal",
            "is_suspended",
            "probable_spammer",
            "is_verified",
            "moderator",
            "reputation",
            "subscribed",
            "updated_date",
            "upload_tutorial_complete",
            "hub_rep",
            "time_rep",
        ]

    def get_balance(self, obj):
        if (
            not self.read_only
            and self.context.get("user")
            and self.context["user"].id == obj.id
        ):
            return obj.get_balance()

    def get_subscribed(self, obj):
        if self.context.get("get_subscribed"):
            hub_context = {
                "hub_shs_get_editor_permission_groups": {"_exclude_fields": "__all__"}
            }
            subscribed_query = obj.subscribed_hubs.all()
            return HubSerializer(subscribed_query, many=True, context=hub_context).data

    def get_hub_rep(self, obj):
        try:
            return obj.hub_rep
        except Exception:
            return None

    def get_time_rep(self, obj):
        time_rep = getattr(obj, "time_rep", None)
        return time_rep


class MinimalUserSerializer(ModelSerializer):
    author_profile = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "author_profile",
            "first_name",
            "last_name",
            "reputation",
        ]

    def get_author_profile(self, obj):
        serializer = AuthorSerializer(
            obj.author_profile, read_only=True, context=self.context
        )
        return serializer.data


class UserEditableSerializer(ModelSerializer):
    author_profile = AuthorSerializer()
    balance = SerializerMethodField()
    balance_history = SerializerMethodField()
    email = SerializerMethodField()
    organization_slug = SerializerMethodField()
    subscribed = SerializerMethodField()
    auth_provider = SerializerMethodField()
    is_verified_v2 = SerializerMethodField()

    class Meta:
        model = User
        exclude = [
            "password",
            "groups",
            "is_superuser",
            "is_staff",
            "user_permissions",
            "username",
            "clicked_on_balance_date",
            "suspended_updated_date",
            "sift_risk_score",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["moderator", "referral_code"]

    def get_auth_provider(self, obj):
        social_account = obj.socialaccount_set.first()
        if social_account:
            return social_account.provider
        else:
            return "email"

    def get_email(self, user):
        context = self.context
        request_user = context.get("user", None)
        if request_user and request_user == user:
            return user.email
        return None

    def get_balance(self, user):
        context = self.context
        request_user = context.get("user", None)

        if request_user and request_user == user:
            return user.get_balance()
        return None

    def get_balance_history(self, user):
        context = self.context
        request_user = context.get("user", None)

        if request_user and request_user == user:
            clicked_on_balance_date = user.clicked_on_balance_date
            balances = user.get_balance_qs()
            balances = balances.filter(created_date__gt=clicked_on_balance_date)
            balance = user.get_balance(balances)
            return balance
        return None

    # FIXME: is_verified_v2 should be available on user model and not on author. This is a shim for legacy reasons.
    def get_is_verified_v2(self, user):
        user_verification = UserVerification.objects.filter(user=user).first()
        return user_verification.is_verified if user_verification else False

    def get_organization_slug(self, user):
        try:
            return user.organization.slug
        except Exception as e:
            sentry.log_error(e)
            return None

    def get_subscribed(self, user):
        if self.context.get("get_subscribed"):
            subscribed_query = user.subscribed_hubs.filter(is_removed=False)
            context = {
                "rag_dps_get_user": {
                    "_include_fields": {"id", "first_name", "last_name"}
                },
                "hub_shs_get_editor_permission_groups": {"_exclude_fields": ["source"]},
            }
            return HubSerializer(subscribed_query, context=context, many=True).data


class RegisterSerializer(rest_auth_serializers.RegisterSerializer):
    username = CharField(
        max_length=rest_auth_serializers.get_username_max_length(),
        min_length=rest_auth_serializers.allauth_settings.USERNAME_MIN_LENGTH,
        required=False,
        allow_blank=True,
    )

    first_name = CharField(max_length=150, allow_blank=True, required=False)
    last_name = CharField(max_length=150, allow_blank=True, required=False)

    def validate_username(self, username):
        if username:
            username = rest_auth_serializers.get_adapter().clean_username(username)
        return username

    def validate_first_name(self, first_name):
        return first_name

    def validate_last_name(self, last_name):
        return last_name

    def get_cleaned_data(self):
        return {
            "username": self.validated_data.get("username", ""),
            "password1": self.validated_data.get("password1", ""),
            "email": self.validated_data.get("email", ""),
            "first_name": self.validated_data.get("first_name"),
            "last_name": self.validated_data.get("last_name"),
        }

    def save(self, request):
        return super().save(request)


class DynamicUserSerializer(DynamicModelFieldSerializer):
    author_profile = SerializerMethodField()
    rsc_earned = SerializerMethodField()
    benefits_expire_on = SerializerMethodField()
    editor_of = SerializerMethodField()

    class Meta:
        model = User
        exclude = ("password",)

    def get_author_profile(self, user):
        context = self.context
        _context_fields = context.get("usr_dus_get_author_profile", {})
        try:
            serializer = DynamicAuthorSerializer(
                user.author_profile, context=context, **_context_fields
            )
            return serializer.data
        except Exception as e:
            print(e)
            sentry.log_error(e)
            return {}

    def get_rsc_earned(self, user):
        return getattr(user, "rsc_earned", None)

    def get_benefits_expire_on(self, user):
        return getattr(user, "benefits_expire_on", None)

    def get_editor_of(self, user):
        context = self.context
        _context_fields = context.get("usr_dus_get_editor_of", {})

        if hasattr(user, "created_by_permissions"):
            # This comes from prefetching
            permissions = user.created_by_permissions
        else:
            hub_content_type = ContentType.objects.get_for_model(Hub)
            permissions = user.permissions.prefetch_related("source").filter(
                access_type=EDITOR,
                content_type=hub_content_type,
            )
        serializer = DynamicPermissionSerializer(
            permissions, many=True, context=context, **_context_fields
        )
        return serializer.data


class UserActions:
    def __init__(self, data=None, user=None, **kwargs):
        assert (data is not None) or (user is not None), f"Arguments data"
        f" and user_id can not both be None"

        self.user = None
        if user and user.is_authenticated:
            self.user = user

        self.all = data
        if data is None:
            self.all = self.get_actions()

        self.serialized = []
        self._group_and_serialize_actions()

    def get_actions(self):
        if self.user:
            return self.user.actions.all()
        else:
            return Action.objects.all()

    def _group_and_serialize_actions(self):
        # TODO: Refactor to clean this up
        from researchhub_document.serializers import (
            ResearchhubUnifiedDocumentSerializer,
        )

        for action in self.all:
            item = action.item
            if not item:
                continue

            creator = self._get_serialized_creator(item)

            data = {
                "created_by": creator,
                "content_type": str(action.content_type),
                "created_date": str(action.created_date),
            }

            if (
                isinstance(item, Comment)
                or isinstance(item, Thread)
                or isinstance(item, Reply)
                or isinstance(item, Summary)
                or isinstance(item, Paper)
            ):
                pass
            elif isinstance(item, BulletPoint):
                data["content_type"] = "bullet_point"
            elif isinstance(item, GrmVote):
                item = item.item
                if isinstance(item, Comment):
                    data["content_type"] += "_comment"
                elif isinstance(item, Reply):
                    data["content_type"] += "_reply"
                elif isinstance(item, Thread):
                    data["content_type"] += "_thread"
                elif isinstance(item, Paper):
                    data["content_type"] += "_paper"
            elif isinstance(item, Purchase):
                recipient = action.user
                data["amount"] = item.amount
                data["recipient"] = {
                    "name": recipient.full_name(),
                    "author_id": recipient.author_profile.id,
                }
                data["sender"] = item.user.full_name()
                data["support_type"] = item.content_type.model
            elif isinstance(item, ResearchhubPost):
                data["post_title"] = item.title
            elif isinstance(item, Bounty):
                item = item.item
            elif isinstance(item, Verdict):
                item = item.flag.item
            elif isinstance(item, BulletVote):
                item = item.bulletpoint
            elif isinstance(item, SummaryVote):
                item = item.summary
            else:
                raise TypeError(f"Instance of type {type(item)} is not supported")

            is_removed = False
            paper = None
            post = None
            discussion = None
            if isinstance(item, Paper):
                paper = item
            else:
                try:
                    if isinstance(item, Purchase):
                        purchase_item = item.item
                        if isinstance(purchase_item, Paper):
                            paper = purchase_item
                        elif isinstance(purchase_item, ResearchhubPost):
                            post = purchase_item
                        elif (
                            isinstance(purchase_item, Thread)
                            or isinstance(purchase_item, Comment)
                            or isinstance(purchase_item, Reply)
                        ):
                            discussion = purchase_item
                        else:
                            paper = purchase_item.paper
                    else:
                        paper = item.paper
                except Exception as e:
                    logging.warning(str(e))

            if paper:
                data["paper_id"] = paper.id
                data["paper_title"] = paper.title
                data["paper_official_title"] = paper.paper_title
                data["slug"] = paper.slug

                if paper.is_removed:
                    is_removed = True

            if post:
                data["post_id"] = post.id
                data["post_title"] = post.title
                data["slug"] = post.slug

            if discussion:
                data["plain_text"] = discussion.plain_text
                paper = discussion.paper
                post = discussion.post
                if paper:
                    data["parent_content_type"] = "paper"
                    data["paper_id"] = paper.id
                    data["paper_title"] = paper.title
                    data["paper_official_title"] = paper.paper_title
                    data["slug"] = paper.slug
                elif post:
                    data["parent_content_type"] = "post"
                    data["post_id"] = post.id
                    data["post_title"] = post.title
                    data["slug"] = post.slug

            if isinstance(item, Thread):
                thread = item
                data["thread_id"] = thread.id
                data["thread_title"] = thread.title
                data["thread_plain_text"] = thread.plain_text
                data["tip"] = item.plain_text
                thread_paper = thread.paper
                thread_post = thread.post
                if thread_paper:
                    data["parent_content_type"] = "paper"
                    data["paper_title"] = thread_paper.title
                    data["paper_id"] = thread_paper.id
                elif thread_post:
                    data["parent_content_type"] = "post"
                    data[
                        "paper_title"
                    ] = (
                        thread_post.title
                    )  # paper_title instead of post_title for symmetry on the FE
                    data[
                        "paper_id"
                    ] = (
                        thread_post.id
                    )  # paper_id instead of post_id to temporarily reduce refactoring on FE

            elif isinstance(item, Paper):
                data["tip"] = item.tagline
            elif check_is_discussion_item(item):
                try:
                    thread = item.thread
                    data["thread_id"] = thread.id
                    data["thread_title"] = thread.title
                    data["thread_plain_text"] = thread.plain_text
                except Exception as e:
                    print(e)
                    pass
                data["tip"] = item.plain_text
            elif isinstance(item, BulletPoint):
                data["tip"] = item.plain_text

            if not isinstance(item, Summary) and not isinstance(item, Purchase):
                data["user_flag"] = None
                if self.user:
                    user_flag = item.flags.filter(created_by=self.user).first()
                    if user_flag:
                        if isinstance(item, Paper):
                            data["user_flag"] = UserActions.paper_flag_serializer(
                                user_flag
                            ).data  # noqa: E501
                        else:
                            data["user_flag"] = UserActions.flag_serializer(
                                user_flag
                            ).data  # noqa: E501

            if isinstance(item, BulletPoint) or check_is_discussion_item(item):
                data["is_removed"] = item.is_removed

            if isinstance(item, Comment):
                data["comment_id"] = item.id
            elif isinstance(item, Reply):
                comment = item.get_comment_of_reply()
                if comment is not None:
                    data["comment_id"] = comment.id
                data["reply_id"] = item.id

            if hasattr(item, "unified_document"):
                unified_document = item.unified_document
                data["unified_document"] = ResearchhubUnifiedDocumentSerializer(
                    unified_document
                ).data

            if not is_removed:
                self.serialized.append(data)

    def _get_serialized_creator(self, item):
        if isinstance(item, Summary):
            creator = item.proposed_by
        elif isinstance(item, Paper):
            creator = item.uploaded_by
        elif isinstance(item, User):
            creator = item
        elif isinstance(item, Purchase):
            creator = item.user
        else:
            creator = item.created_by
        if creator is not None:
            return UserSerializer(creator).data
        return None


class DynamicActionSerializer(DynamicModelFieldSerializer):
    item = SerializerMethodField()
    content_type = SerializerMethodField()
    created_by = SerializerMethodField()
    hubs = SerializerMethodField()
    reason = SerializerMethodField()

    class Meta:
        model = Action
        fields = "__all__"

    def get_item(self, action):
        context = self.context
        _context_fields = context.get("usr_das_get_item", {})
        item = action.item
        ignored_items = (BulletPoint, BulletVote, Summary, SummaryVote)
        if isinstance(item, ignored_items):
            return None

        if isinstance(item, Withdrawal):
            # @patrick
            # https://github.com/ResearchHub/researchhub-backend/pull/990#discussion_r819213890
            from reputation.serializers import WithdrawalSerializer

            serializer = WithdrawalSerializer
            context = {}
            _context_fields = {}
        elif isinstance(item, Paper):
            from paper.serializers import DynamicPaperSerializer

            serializer = DynamicPaperSerializer
        elif isinstance(item, ResearchhubPost):
            from researchhub_document.serializers import DynamicPostSerializer

            serializer = DynamicPostSerializer
        elif isinstance(item, Hypothesis):
            from hypothesis.serializers import DynamicHypothesisSerializer

            serializer = DynamicHypothesisSerializer
        elif isinstance(item, Purchase):
            from purchase.serializers import DynamicPurchaseSerializer

            serializer = DynamicPurchaseSerializer
        elif isinstance(item, RhCommentModel):
            from researchhub_comment.serializers import DynamicRhCommentSerializer

            serializer = DynamicRhCommentSerializer
        elif isinstance(item, Thread):
            from discussion.serializers import DynamicThreadSerializer

            serializer = DynamicThreadSerializer
        elif isinstance(item, Comment):
            from discussion.serializers import DynamicCommentSerializer

            serializer = DynamicCommentSerializer
        elif isinstance(item, Reply):
            from discussion.serializers import DynamicReplySerializer

            serializer = DynamicReplySerializer
        elif isinstance(item, PaperSubmission):
            from paper.serializers import DynamicPaperSubmissionSerializer

            serializer = DynamicPaperSubmissionSerializer
        elif isinstance(item, Verdict):
            serializer = DynamicVerdictSerializer
        elif isinstance(item, Bounty):
            from reputation.serializers import DynamicBountySerializer

            serializer = DynamicBountySerializer
        else:
            return None

        data = serializer(item, context=context, **_context_fields).data

        return data

    def get_created_by(self, action):
        context = self.context
        _context_fields = context.get("usr_das_get_created_by", {})
        serializer = DynamicUserSerializer(
            action.user, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, action):
        content_type = action.content_type
        return {"id": content_type.id, "name": content_type.model}

    def get_hubs(self, action):
        context = self.context
        _context_fields = context.get("usr_das_get_hubs", {})
        serializer = DynamicHubSerializer(
            action.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_reason(self, action):
        return getattr(action, "reason", None)


class OrganizationSerializer(ModelSerializer):
    member_count = SerializerMethodField()
    user_permission = SerializerMethodField()

    class Meta:
        model = Organization
        fields = "__all__"
        read_only_fields = ["id", "slug"]

    def get_member_count(self, organization):
        permissions = organization.permissions
        users = permissions.filter(user__isnull=False)
        return users.count()

    def get_user_permission(self, organization):
        context = self.context

        if "request" in context:
            request = context.get("request")
            user = request.user
        else:
            return None

        if not user.is_anonymous:
            permission = organization.permissions.filter(user=user)
            if permission.exists():
                permission = permission.first()
            else:
                return None
            access_type = permission.access_type
            return {"access_type": access_type}
        return None


class DynamicOrganizationSerializer(DynamicModelFieldSerializer):
    member_count = SerializerMethodField()
    user = SerializerMethodField()
    user_permission = SerializerMethodField()

    class Meta:
        model = Organization
        fields = "__all__"

    def get_member_count(self, organization):
        permissions = organization.permissions
        users = permissions.filter(user__isnull=False)
        return users.count()

    def get_user(self, organization):
        context = self.context
        _context_fields = context.get("usr_dos_get_user", {})

        serializer = DynamicUserSerializer(
            organization.user, context=context, **_context_fields
        )
        return serializer.data

    def get_user_permission(self, organization):
        context = self.context
        _context_fields = context.get("usr_dos_get_user_permissions", {})
        user = context.get("user")

        permission = organization.permissions.filter(user=user)
        if permission.exists():
            permission = permission.first()
        else:
            return None

        serializer = DynamicPermissionSerializer(
            permission, context=context, **_context_fields
        )
        return serializer.data


class VerdictSerializer(ModelSerializer):
    class Meta:
        model = Verdict
        fields = "__all__"


class DynamicVerdictSerializer(DynamicModelFieldSerializer):
    created_by = SerializerMethodField()
    flag = SerializerMethodField()
    flagged_content_name = SerializerMethodField()

    class Meta:
        model = Verdict
        fields = "__all__"

    def get_created_by(self, verdict):
        context = self.context
        _context_fields = context.get("usr_dvs_get_created_by", {})

        serializer = DynamicUserSerializer(
            verdict.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_flag(self, verdict):
        from discussion.serializers import DynamicFlagSerializer

        context = self.context
        _context_fields = context.get("usr_dvs_get_flag", {})

        serializer = DynamicFlagSerializer(
            verdict.flag, context=context, **_context_fields
        )
        return serializer.data

    def get_flagged_content_name(self, verdict):
        return verdict.flag.content_type.name


class DynamicAuthorInstitutionSerializer(DynamicModelFieldSerializer):
    institution = SerializerMethodField()

    class Meta:
        model = AuthorInstitution
        fields = "__all__"

    def get_institution(self, author_institution):
        context = self.context
        _context_fields = context.get("author_institution::get_institution", {})

        institution = author_institution.institution
        serializer = DynamicInstitutionSerializer(
            institution, context=context, **_context_fields
        )
        return serializer.data


class DynamicCoAuthorSerializer(DynamicModelFieldSerializer):
    coauthor = SerializerMethodField()

    class Meta:
        model = CoAuthor
        fields = "__all__"

    def get_coauthor(self, coauthor):
        context = self.context
        _context_fields = context.get("coauthor::get_coauthor", {})

        serializer = DynamicAuthorSerializer(
            coauthor.coauthor, context=context, **_context_fields
        )
        return serializer.data


class DynamicAuthorProfileSerializer(DynamicModelFieldSerializer):
    institutions = SerializerMethodField()
    coauthors = SerializerMethodField()
    reputation = SerializerMethodField()
    reputation_list = SerializerMethodField()
    activity_by_year = SerializerMethodField()
    summary_stats = SerializerMethodField()
    open_access_pct = SerializerMethodField()
    achievements = SerializerMethodField()
    headline = SerializerMethodField()
    user = SerializerMethodField()

    class Meta:
        model = Author
        fields = "__all__"

    def get_headline(self, author):
        from collections import Counter

        if author.headline:
            return author.headline

        try:
            all_topics = []
            authored_papers = author.authored_papers.all()

            for p in authored_papers:
                unified_document = p.unified_document
                all_topics += list(unified_document.topics.all())

            topic_counts = Counter(all_topics)

            # Sort topics by frequency
            sorted_topics = sorted(
                topic_counts.items(), key=lambda x: x[1], reverse=True
            )

            # Extract topics from sorted list
            sorted_topics = [topic for topic, _ in sorted_topics]

            if not sorted_topics:
                return None

            return {
                "title": "Author with expertise in " + sorted_topics[0].display_name
            }
        except Exception:
            return None

    def get_user(self, author):
        user = author.user

        if user is None:
            return None

        is_verified = False
        user_verification = UserVerification.objects.filter(user=user).first()
        if user_verification:
            is_verified = user_verification.is_verified

        return {
            "id": user.id,
            "created_date": user.created_date,
            "is_verified": is_verified,
        }

    def get_achievements(self, author):
        summary_stats = self.get_summary_stats(author)
        open_access_pct = self.get_open_access_pct(author)

        achievements = []
        if summary_stats["citation_count"] >= 1:
            achievements.append("CITED_AUTHOR")
        if open_access_pct >= 0.5:
            achievements.append("OPEN_ACCESS")
        if summary_stats["upvote_count"] >= 10:
            achievements.append("HIGHLY_UPVOTED_1")
        if summary_stats["upvote_count"] >= 25:
            achievements.append("HIGHLY_UPVOTED_2")
        if summary_stats["upvote_count"] >= 100:
            achievements.append("HIGHLY_UPVOTED_3")
        if summary_stats["upvote_count"] >= 500:
            achievements.append("HIGHLY_UPVOTED_4")
        if summary_stats["upvote_count"] >= 1000:
            achievements.append("HIGHLY_UPVOTED_5")
        if summary_stats["peer_review_count"] >= 1:
            achievements.append("EXPERT_PEER_REVIEWER_1")
        if summary_stats["peer_review_count"] >= 5:
            achievements.append("EXPERT_PEER_REVIEWER_2")
        if summary_stats["peer_review_count"] >= 25:
            achievements.append("EXPERT_PEER_REVIEWER_3")
        if summary_stats["peer_review_count"] >= 100:
            achievements.append("EXPERT_PEER_REVIEWER_4")
        if summary_stats["peer_review_count"] >= 250:
            achievements.append("EXPERT_PEER_REVIEWER_5")
        if summary_stats["amount_funded"] > 1:
            achievements.append("OPEN_SCIENCE_SUPPORTER")

        return achievements

    def get_summary_stats(self, author: Author):
        from django.db.models import Count, Sum

        user = author.user

        citation_count, paper_count = (
            Authorship.objects.filter(author=author)
            .aggregate(
                citation_count=Sum("paper__citations"),
                paper_count=Count("paper"),
            )
            .values()
        )

        upvote_count = Distribution.objects.filter(
            recipient=user,
            proof_item_content_type=ContentType.objects.get_for_model(GrmVote),
            reputation_amount=1,
        ).aggregate(count=Count("id"))["count"]

        amount_funded = Bounty.objects.filter(
            created_by=user,
            status=Bounty.CLOSED,
        ).aggregate(total_amount=Sum("amount"))["total_amount"]

        peer_review_count = RhCommentModel.objects.filter(
            created_by=user,
            comment_type="REVIEW",
            is_removed=False,
        ).aggregate(count=Count("id"))["count"]

        return {
            "works_count": paper_count or 0,
            "citation_count": citation_count or 0,
            "two_year_mean_citedness": author.two_year_mean_citedness or 0,
            "upvote_count": upvote_count or 0,
            "amount_funded": amount_funded or 0,
            "peer_review_count": peer_review_count or 0,
        }

    def get_activity_by_year(self, author):
        context = self.context
        _context_fields = context.get("author_profile::activity_by_year", {})

        serializer = DynamicAuthorContributionSummarySerializer(
            author.contribution_summaries.all(),
            context=context,
            many=True,
            **_context_fields,
        )
        return serializer.data

    def get_open_access_pct(self, author):
        total_paper_count = author.authored_papers.count()

        if total_paper_count == 0:
            return 0
        else:
            return (
                author.authored_papers.filter(is_open_access=True).count()
                / total_paper_count
            )

    def get_reputation(self, author):
        score = Score.objects.filter(author=author).order_by("-score").first()

        if score is None:
            return None

        hub = Hub.objects.get(id=score.hub_id)

        return {
            "hub": {
                "id": hub.id,
                "name": hub.name,
                "slug": hub.slug,
            },
            "score": score.score,
            "percentile": score.percentile,
            "bins": [
                [0, 1000],
                [1000, 10000],
                [10000, 100000],
                [100000, 1000000],
            ],  # FIXME: Replace with bins from algo vars table
        }

    def get_reputation_list(self, author):
        scores = Score.objects.filter(author=author, score__gt=0).order_by("-score")
        reputation_list = []
        for score in scores:
            hub = Hub.objects.get(id=score.hub_id)
            reputation_list.append(
                {
                    "hub": {
                        "id": hub.id,
                        "name": hub.name,
                        "slug": hub.slug,
                    },
                    "score": score.score,
                    "percentile": score.percentile,
                    "bins": [
                        [0, 1000],
                        [1000, 10000],
                        [10000, 100000],
                        [100000, 1000000],
                    ],  # FIXME: Replace with bins from algo vars table
                }
            )

        return reputation_list

    def get_institutions(self, author):
        context = self.context
        _context_fields = context.get("author_profile::get_institutions", {})

        serializer = DynamicAuthorInstitutionSerializer(
            author.institutions, context=context, many=True, **_context_fields
        )
        return serializer.data

    def get_coauthors(self, author):
        from django.db.models import Count

        context = self.context
        _context_fields = context.get("author_profile::get_coauthors", {})

        coauthors = (
            CoAuthor.objects.filter(author=author)
            .values(
                "coauthor",
                "coauthor__first_name",
                "coauthor__last_name",
                "coauthor__is_verified",
                "coauthor__headline",
                "coauthor__description",
            )
            .annotate(count=Count("coauthor"))
            .order_by("-count")[:10]
        )

        coauthor_data = [
            {
                "id": co["coauthor"],
                "first_name": co["coauthor__first_name"],
                "last_name": co["coauthor__last_name"],
                "is_verified": co["coauthor__is_verified"],
                "headline": co["coauthor__headline"],
                "description": co["coauthor__description"],
                "count": co["count"],
            }
            for co in coauthors
        ]

        serializer = DynamicAuthorSerializer(
            coauthor_data,
            context=context,
            many=True,
            **_context_fields,
        )
        return serializer.data


class DynamicAuthorContributionSummarySerializer(DynamicModelFieldSerializer):
    class Meta:
        model = AuthorContributionSummary
        fields = "__all__"
