import dj_rest_auth.registration.serializers as rest_auth_serializers
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from rest_framework import serializers
from rest_framework.serializers import (
    CharField,
    IntegerField,
    ModelSerializer,
    PrimaryKeyRelatedField,
    SerializerMethodField,
)

from hub.models import Hub
from hub.serializers import DynamicHubSerializer, HubSerializer, SimpleHubSerializer
from institution.serializers import DynamicInstitutionSerializer
from paper.models import Paper, PaperSubmission
from purchase.models import Purchase
from referral.models import ReferralSignup
from reputation.models import Bounty, Contribution, Score, Withdrawal
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    EDITOR,
    SENIOR_EDITOR,
)
from researchhub_access_group.serializers import DynamicPermissionSerializer
from researchhub_comment.models import RhCommentModel
from researchhub_document.models import ResearchhubPost
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
from user.related_models.follow_model import Follow
from user.related_models.gatekeeper_model import Gatekeeper
from utils import sentry


class ModeratorUserSerializer(ModelSerializer):
    verification = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "probable_spammer",
            "is_suspended",
            "verification",
            "created_date",
        ]

    def get_verification(self, user):
        try:
            user_verification = user.userverification
        except UserVerification.DoesNotExist:
            return None

        return {
            "first_name": user_verification.first_name,
            "last_name": user_verification.last_name,
            "created_date": user_verification.created_date,
            "verified_by": user_verification.verified_by,
            "external_id": user_verification.external_id,
            "status": user_verification.status,
        }


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
    total_score = SerializerMethodField()
    university = UniversitySerializer(required=False)
    wallet = SerializerMethodField()
    suspended_status = SerializerMethodField()
    is_verified = SerializerMethodField()

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

    def get_is_verified(self, obj):
        return obj.is_verified

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
        return author.reputation_list

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
            (
                Q(access_type=ASSISTANT_EDITOR)
                | Q(access_type=ASSOCIATE_EDITOR)
                | Q(access_type=SENIOR_EDITOR)
            ),
            content_type=hub_content_type,
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
    is_verified = SerializerMethodField()

    class Meta:
        model = Author
        fields = "__all__"

    def get_is_verified(self, obj):
        return obj.is_verified


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


class FollowSerializer(serializers.ModelSerializer):
    content_type = serializers.SlugRelatedField(
        queryset=ContentType.objects.filter(model__in=Follow.ALLOWED_FOLLOW_MODELS),
        slug_field="model",
        write_only=True,
    )
    type = serializers.SerializerMethodField()
    followed_object = serializers.SerializerMethodField()

    class Meta:
        model = Follow
        fields = (
            "id",
            "content_type",
            "type",
            "object_id",
            "followed_object",
            "created_date",
            "updated_date",
        )
        read_only_fields = ("id", "created_date", "updated_date", "type")

    def get_type(self, obj):
        """
        Return simplified content type string
        """
        model = obj.content_type.model
        return model.upper()

    def get_followed_object(self, obj):
        if obj.content_type.model == "hub":
            return HubSerializer(obj.followed_object).data
        return None

    def validate(self, data):
        """
        Check that the content_type is allowed for following.
        """
        if data["content_type"].model not in Follow.ALLOWED_FOLLOW_MODELS:
            raise serializers.ValidationError(
                f"Cannot follow objects of type {data['content_type'].model}"
            )
        return data

    def create(self, validated_data):
        """
        Create a new follow instance.
        """
        user = self.context["request"].user
        validated_data["user"] = user
        return super().create(validated_data)


class UserSerializer(ModelSerializer):
    author_profile = AuthorSerializer(read_only=True)
    balance = SerializerMethodField(read_only=True)
    subscribed = SerializerMethodField(read_only=True)
    hub_rep = SerializerMethodField()
    time_rep = SerializerMethodField()
    is_verified = SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "author_profile",
            "balance",
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
        read_only_fields = [
            "id",
            "author_profile",
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

    def get_is_verified(self, obj):
        return obj.is_verified


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
    locked_balance = SerializerMethodField()
    balance_history = SerializerMethodField()
    email = SerializerMethodField()
    organization_slug = SerializerMethodField()
    subscribed = SerializerMethodField()
    auth_provider = SerializerMethodField()
    is_verified = SerializerMethodField()

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

    def get_locked_balance(self, user):
        context = self.context
        request_user = context.get("user", None)
        if request_user and request_user == user:
            return user.get_locked_balance()
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

    def get_is_verified(self, user):
        return user.is_verified

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
    referral_code = CharField(max_length=100, allow_blank=True, required=False)

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
            "referral_code": self.validated_data.get("referral_code"),
        }

    def save(self, request):
        user = super().save(request)

        # Handle referral signup creation
        referral_code = self.validated_data.get("referral_code")
        if referral_code and referral_code.strip():
            try:
                # Find the referrer by their referral code
                referrer = User.objects.get(referral_code=referral_code.strip())
                # Create the referral signup entry
                ReferralSignup.objects.create(referrer=referrer, referred=user)
            except User.DoesNotExist:
                pass

        return user


class DynamicUserSerializer(DynamicModelFieldSerializer):
    author_profile = SerializerMethodField()
    rsc_earned = SerializerMethodField()
    benefits_expire_on = SerializerMethodField()
    editor_of = SerializerMethodField()
    is_verified = SerializerMethodField()

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

    def get_is_verified(self, user):
        return user.is_verified


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
        elif isinstance(item, Purchase):
            from purchase.serializers import DynamicPurchaseSerializer

            serializer = DynamicPurchaseSerializer
        elif isinstance(item, RhCommentModel):
            from researchhub_comment.serializers import DynamicRhCommentSerializer

            serializer = DynamicRhCommentSerializer
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
    achievements = SerializerMethodField()
    headline = SerializerMethodField()
    user = SerializerMethodField()

    class Meta:
        model = Author
        fields = "__all__"

    def get_achievements(self, author):
        return author.achievements

    def get_headline(self, author):
        return author.build_headline()

    def get_user(self, author):
        user = author.user

        if user is None:
            return None

        return {
            "id": user.id,
            "created_date": user.created_date,
            "is_verified": user.is_verified,
            "is_suspended": user.is_suspended,
            "probable_spammer": user.probable_spammer,
        }

    def get_summary_stats(self, author):
        stats = {
            "works_count": author.paper_count,
            "citation_count": author.citation_count,
            "two_year_mean_citedness": author.two_year_mean_citedness or 0,
            "upvote_count": author.user.upvote_count if author.user else 0,
            "amount_funded": author.user.amount_funded if author.user else 0,
            "peer_review_count": author.user.peer_review_count if author.user else 0,
            "open_access_pct": author.open_access_pct,
        }

        return stats

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
        scores = (
            Score.objects.filter(author=author, score__gt=0)
            .select_related("hub")
            .order_by("-score")
        )
        reputation_list = [
            {
                "hub": {
                    "id": score.hub.id,
                    "name": score.hub.name,
                    "slug": score.hub.slug,
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
            for score in scores
        ]

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
            Author.objects.filter(coauthored_with__author=author)
            .annotate(count=Count("coauthored_with"))
            .select_related("user__userverification")
            .order_by("-count")[:10]
        )

        serializer = DynamicAuthorSerializer(
            coauthors,
            context=context,
            many=True,
            **_context_fields,
        )
        return serializer.data


class DynamicAuthorContributionSummarySerializer(DynamicModelFieldSerializer):
    class Meta:
        model = AuthorContributionSummary
        fields = "__all__"
