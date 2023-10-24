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
from paper.models import Paper, PaperSubmission
from purchase.models import Purchase
from reputation.models import Bounty, Contribution, Withdrawal
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
    Verdict,
    Verification,
    VerificationFile,
)
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
    sift_link = SerializerMethodField()
    total_score = SerializerMethodField()
    university = UniversitySerializer(required=False)
    wallet = SerializerMethodField()

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
            "sift_link",
            "total_score",
            "university",
            "wallet",
            "is_verified",
        ]
        read_only_fields = [
            "added_as_editor_date",
            "claimed_by_user_author_id",
            "is_claimed",
            "is_hub_editor_of",
            "num_posts",
            "merged_with",
            "is_verified",
        ]

    def get_reputation(self, obj):
        if obj.user is None:
            return 0
        return obj.user.reputation

    def get_orcid_id(self, author):
        return author.orcid_id

    def get_total_score(self, author):
        if author.author_score > 0:
            return author.author_score
        # else:
        #     raw_score = Paper.objects.filter(
        #         raw_authors__contains=[
        #             {
        #                 'first_name': author.first_name,
        #                 'last_name': author.last_name
        #             }
        #         ]
        #     ).aggregate(
        #         Sum('score')
        #     ).get('score__sum', 0) or 0

        #     authored_score = author.authored_papers.aggregate(Sum('score')).get('score__sum', 0) or 0
        #     total = raw_score + authored_score

        #     if total > 0:
        #         author.author_score = total
        #         author.save()
        #     return total

    def get_wallet(self, obj):
        from purchase.serializers import WalletSerializer

        if not self.context.get("include_wallet", False):
            return

        try:
            return WalletSerializer(obj.wallet).data
        except Exception as error:
            # sentry.log_error(error)
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


class VerificationFileSerializer(ModelSerializer):
    class Meta:
        model = VerificationFile
        fields = "__all__"


class VerificationSerializer(ModelSerializer):
    files = VerificationFileSerializer(many=True, read_only=True)
    related_author_object = SerializerMethodField()

    class Meta:
        model = Verification
        fields = "__all__"

    def get_related_author_object(self, obj):
        return AuthorSerializer(obj.related_author).data


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
    is_verified = SerializerMethodField()

    class Meta:
        model = Author
        fields = "__all__"

    def get_is_verified(self, author):
        return author.user.is_verified


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
            "probable_spammer",
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
