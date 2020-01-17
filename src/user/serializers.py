import rest_framework.serializers as rest_framework_serializers
import rest_auth.registration.serializers as rest_auth_serializers

import reputation.lib
from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from hub.serializers import HubSerializer
from paper.models import Vote as PaperVote
from user.models import Author, University, User


class UniversitySerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = University
        fields = '__all__'


class AuthorSerializer(rest_framework_serializers.ModelSerializer):
    university = UniversitySerializer(required=False)
    reputation = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = [field.name for field in Author._meta.fields] + [
            'university',
            'reputation',
        ]

    def get_reputation(self, obj):
        if obj.user is None:
            return 0
        return obj.user.reputation


class UserSerializer(rest_framework_serializers.ModelSerializer):
    author_profile = AuthorSerializer()
    balance = rest_framework_serializers.SerializerMethodField()
    subscribed = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = User
        exclude = ['password', 'groups', 'is_superuser', 'is_staff', 'user_permissions']

    def get_balance(self, obj):
        return reputation.lib.get_user_balance(obj)

    def get_subscribed(self, obj):
        if self.context.get('get_subscribed'):
            subscribed_query = obj.subscribed_hubs.all()
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
    # Using local imports to avoid circular dependency error
    from discussion.serializers import (
        CommentSerializer,
        ReplySerializer,
        ThreadSerializer,
        VoteSerializer as DiscussionVoteSerializer
    )
    from paper.serializers import VoteSerializer as PaperVoteSerializer

    def __init__(self, data, is_user_id=True, **kwargs):
        self.all = []
        if is_user_id:
            self.all = self.get_actions(data)
        else:
            self.all = data
        self.serialized = []
        self.comments = []
        self.replies = []
        self.threads = []
        self.discussion_votes = []
        self.paper_votes = []
        self._group_and_serialize_actions()

    @property
    def actions_by_type(self):
        return {
            'comments': self.comments,
            'replies': self.replies,
            'threads': self.threads,
            'discussion_votes': self.discussion_votes,
            'paper_votes': self.paper_votes,
        }

    def get_actions(self, user_id):
        user = User.objects.get(pk=user_id)
        return user.actions.all()

    def _group_and_serialize_actions(self):
        for action in self.all:
            item = action.item
            if isinstance(item, Comment):
                self.comments.append(item)
                data = self.CommentSerializer(item).data
                data['content_type'] = str(action.content_type)
                self.serialized.append(data)

            elif isinstance(item, Reply):
                self.replies.append(item)
                data = self.ReplySerializer(item).data
                data['content_type'] = str(action.content_type)
                self.serialized.append(data)

            elif isinstance(item, Thread):
                self.threads.append(item)
                data = self.ThreadSerializer(item).data
                data['content_type'] = str(action.content_type)
                self.serialized.append(data)

            elif isinstance(item, DiscussionVote):
                self.discussion_votes.append(item)
                data = self.DiscussionVoteSerializer(item).data
                data['content_type'] = str(action.content_type)
                self.serialized.append(data)

            elif isinstance(item, PaperVote):
                self.paper_votes.append(item)
                data = self.PaperVoteSerializer(item).data
                data['content_type'] = str(action.content_type)
                self.serialized.append(data)

            else:
                raise TypeError(
                    f'Instance of type {type(item)} is not supported'
                )
