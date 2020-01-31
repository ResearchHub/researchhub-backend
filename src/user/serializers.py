import rest_framework.serializers as rest_framework_serializers
import rest_auth.registration.serializers as rest_auth_serializers

import reputation.lib
from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from hub.serializers import HubSerializer
from paper.models import Paper, Vote as PaperVote
from user.models import Author, University, User
from summary.models import Summary
from discussion.models import ContentType

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
        exclude = [
            'password',
            'groups',
            'is_superuser',
            'is_staff',
            'user_permissions'
        ]

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
    def __init__(self, data=None, user_id=None, **kwargs):
        assert (data is not None) or (user_id is not None), f'Arguments data'
        f' and user_id can not both be None'

        self.all = data
        if data is None:
            self.all = self.get_actions(user_id)

        self.serialized = []
        self._group_and_serialize_actions()

    def get_actions(self, user_id):
        user = User.objects.get(pk=user_id)
        return user.actions.all()

    def _group_and_serialize_actions(self):
        # TODO: Refactor this to only get the data we need instead of
        # serializing everything
        #
        # user object, thread id, paper id, action timestamp
        for action in self.all:
            item = action.item
            if not item:
                continue

            if isinstance(item, Summary):
                created_by = UserSerializer(item.proposed_by).data
            elif item:
                created_by = UserSerializer(item.created_by).data

            data = {
                'created_by': created_by,
                'content_type': str(action.content_type),
                'created_date': action.created_date,
            }
            if isinstance(item, Comment) or isinstance(item, Thread) or isinstance(item, Reply) or isinstance(item, Summary):
                pass
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
            else:
                raise TypeError(
                    f'Instance of type {type(item)} is not supported'
                )

            paper = item.paper
            data['paper_id'] = paper.id
            data['paper_title'] = paper.title

            if isinstance(item, Thread):
                thread = item
                data['thread_id'] = thread.id
                data['thread_title'] = thread.title

                data['tip'] = item.plain_text

            elif not isinstance(item, Summary) and not isinstance(item, PaperVote):
                thread = item.thread

                data['thread_id'] = thread.id
                data['thread_title'] = thread.title

                data['tip'] = item.plain_text

            self.serialized.append(data)
