import logging
import rest_framework.serializers as rest_framework_serializers
import rest_auth.registration.serializers as rest_auth_serializers

from bullet_point.models import BulletPoint
from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from discussion.lib import check_is_discussion_item
from hub.serializers import HubSerializer
from paper.models import Vote as PaperVote, Paper
from user.models import (
    Action,
    Author,
    University,
    User,
    Major,
    Verification
)
from summary.models import Summary
from purchase.models import Purchase
from utils import sentry


class VerificationSerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = Verification
        fields = '__all__'


class UniversitySerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = University
        fields = '__all__'


class MajorSerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = Major
        fields = '__all__'


class AuthorSerializer(rest_framework_serializers.ModelSerializer):
    university = UniversitySerializer(required=False)
    reputation = rest_framework_serializers.SerializerMethodField()
    orcid_id = rest_framework_serializers.SerializerMethodField()
    total_score = rest_framework_serializers.SerializerMethodField()
    wallet = rest_framework_serializers.SerializerMethodField()
    sift_link = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = [field.name for field in Author._meta.fields] + [
            'university',
            'reputation',
            'orcid_id',
            'total_score',
            'wallet',
            'sift_link'
        ]

    def get_reputation(self, obj):
        if obj.user is None:
            return 0
        return obj.user.reputation

    def get_orcid_id(self, author):
        return author.orcid_id

    def get_total_score(self, author):
        return author.author_score

    def get_wallet(self, obj):
        from purchase.serializers import WalletSerializer
        if not self.context.get('include_wallet', True):
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
            sift_link = f'https://console.sift.com/users/{user_id}?abuse_type=content_abuse'
            return sift_link
        return None


class AuthorEditableSerializer(rest_framework_serializers.ModelSerializer):
    university = rest_framework_serializers.PrimaryKeyRelatedField(
        queryset=University.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = Author
        fields = [field.name for field in Author._meta.fields] + ['university']


class UserSerializer(rest_framework_serializers.ModelSerializer):
    author_profile = AuthorSerializer(read_only=True)
    balance = rest_framework_serializers.SerializerMethodField(read_only=True)
    subscribed = rest_framework_serializers.SerializerMethodField(
        read_only=True
    )
    hub_rep = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'author_profile',
            'balance',
            'bookmarks',
            'created_date',
            'has_seen_first_coin_modal',
            'has_seen_orcid_connect_modal',
            'is_suspended',
            'moderator',
            'reputation',
            'subscribed',
            'updated_date',
            'upload_tutorial_complete',
            'hub_rep',
            'probable_spammer',
        ]
        read_only_fields = [
            'id',
            'author_profile',
            'bookmarks',
            'created_date',
            'has_seen_first_coin_modal',
            'has_seen_orcid_connect_modal',
            'is_suspended',
            'moderator',
            'reputation',
            'subscribed',
            'updated_date',
            'upload_tutorial_complete',
            'hub_rep',
        ]

    def get_balance(self, obj):
        if not self.read_only and self.context.get('user') and self.context['user'].id == obj.id:
            return obj.get_balance()

    def get_subscribed(self, obj):
        if self.context.get('get_subscribed'):
            subscribed_query = obj.subscribed_hubs.all()
            return HubSerializer(subscribed_query, many=True).data

    def get_hub_rep(self, obj):
        try:
            return obj.hub_rep
        except Exception:
            return None


class MinimalUserSerializer(rest_framework_serializers.ModelSerializer):
    author_profile = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'author_profile',
        ]

    def get_author_profile(self, obj):
        serializer = AuthorSerializer(
            obj.author_profile,
            read_only=True,
            context=self.context
        )
        return serializer.data


class UserEditableSerializer(rest_framework_serializers.ModelSerializer):
    author_profile = AuthorSerializer()
    balance = rest_framework_serializers.SerializerMethodField()
    subscribed = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = User
        exclude = [
            'password',
            'groups',
            'is_superuser',
            'is_staff',
            'user_permissions',
        ]
        read_only_fields = [
            'moderator',
        ]

    def get_balance(self, obj):
        return obj.get_balance()

    def get_subscribed(self, obj):
        if self.context.get('get_subscribed'):
            subscribed_query = obj.subscribed_hubs.filter(is_removed=False)
            return HubSerializer(subscribed_query, many=True).data


class RegisterSerializer(rest_auth_serializers.RegisterSerializer):
    username = rest_auth_serializers.serializers.CharField(
        max_length=rest_auth_serializers.get_username_max_length(),
        min_length=rest_auth_serializers.allauth_settings.USERNAME_MIN_LENGTH,
        required=False,
        allow_blank=True
    )

    def validate_username(self, username):
        if username:
            username = rest_auth_serializers.get_adapter().clean_username(
                username
            )
        return username

    def save(self, request):
        return super().save(request)


class UserActions:
    def __init__(self, data=None, user=None, **kwargs):
        assert (data is not None) or (user is not None), f'Arguments data'
        f' and user_id can not both be None'

        if not hasattr(UserActions, 'flag_serializer'):
            from discussion.serializers import FlagSerializer
            UserActions.flag_serializer = FlagSerializer

            from paper.serializers import FlagSerializer as PaperFlagSerializer
            UserActions.paper_flag_serializer = PaperFlagSerializer

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
        for action in self.all:
            item = action.item
            if not item:
                continue

            creator = self._get_serialized_creator(item)

            data = {
                'created_by': creator,
                'content_type': str(action.content_type),
                'created_date': str(action.created_date),
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
                data['content_type'] = 'bullet_point'
            elif isinstance(item, DiscussionVote):
                item = item.item
                if isinstance(item, Comment):
                    data['content_type'] += '_comment'
                elif isinstance(item, Reply):
                    data['content_type'] += '_reply'
                elif isinstance(item, Thread):
                    data['content_type'] += '_thread'
            elif isinstance(item, PaperVote):
                data['content_type'] += '_paper'
            elif isinstance(item, Purchase):
                recipient = action.user
                data['amount'] = item.amount
                data['recipient'] = {
                    'name': recipient.full_name(),
                    'author_id': recipient.author_profile.id
                }
                data['sender'] = item.user.full_name()
                data['support_type'] = item.content_type.model
            else:
                continue
                raise TypeError(
                    f'Instance of type {type(item)} is not supported'
                )

            is_removed = False
            paper = None
            if isinstance(item, Paper):
                paper = item
            else:
                try:
                    if isinstance(item, Purchase):
                        purchase_item = item.item
                        if isinstance(purchase_item, Paper):
                            paper = purchase_item
                        else:
                            paper = purchase_item.paper
                    else:
                        paper = item.paper
                except Exception as e:
                    logging.warning(str(e))

            if paper:
                data['paper_id'] = paper.id
                data['paper_title'] = paper.title
                data['paper_official_title'] = paper.paper_title
                data['slug'] = paper.slug

                if paper.is_removed:
                    is_removed = True

            if isinstance(item, Thread):
                thread = item
                data['thread_id'] = thread.id
                data['thread_title'] = thread.title
                data['thread_plain_text'] = thread.plain_text
                data['tip'] = item.plain_text
            elif isinstance(item, Paper):
                data['tip'] = item.tagline
            elif check_is_discussion_item(item):
                try:
                    thread = item.thread
                    data['thread_id'] = thread.id
                    data['thread_title'] = thread.title
                    data['thread_plain_text'] = thread.plain_text
                except Exception as e:
                    print(e)
                    pass
                data['tip'] = item.plain_text
            elif isinstance(item, BulletPoint):
                data['tip'] = item.plain_text

            if not isinstance(item, Summary) and not isinstance(item, Purchase):
                data['user_flag'] = None
                if self.user:
                    user_flag = item.flags.filter(created_by=self.user).first()
                    if user_flag:
                        if isinstance(item, Paper):
                            data['user_flag'] = UserActions.paper_flag_serializer(user_flag).data  # noqa: E501
                        else:
                            data['user_flag'] = UserActions.flag_serializer(user_flag).data  # noqa: E501

            if isinstance(item, BulletPoint) or check_is_discussion_item(item):
                data['is_removed'] = item.is_removed

            if isinstance(item, Comment):
                data['comment_id'] = item.id
            elif isinstance(item, Reply):
                comment = item.get_comment_of_reply()
                if comment is not None:
                    data['comment_id'] = comment.id
                data['reply_id'] = item.id

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
        elif isinstance(item, Purchase):
            creator = item.user
        else:
            creator = item.created_by
        if creator is not None:
            return UserSerializer(creator).data
        return None
