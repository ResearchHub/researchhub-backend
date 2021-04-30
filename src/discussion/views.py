import base64
import hashlib

from django.core.cache import cache
from django.contrib.admin.options import get_content_type_for_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
    IsAuthenticated
)
from rest_framework.response import Response

from utils.throttles import THROTTLE_CLASSES

from discussion.models import (
    BaseComment,
    Comment,
    Endorsement,
    Flag,
    Thread,
    Reply,
    Vote,
)
from .serializers import (
    CommentSerializer,
    EndorsementSerializer,
    FlagSerializer,
    ThreadSerializer,
    ReplySerializer,
    VoteSerializer,
)
from discussion.permissions import (
    CensorDiscussion,
    CreateDiscussionComment,
    CreateDiscussionReply,
    CreateDiscussionThread,
    Endorse,
    FlagDiscussionComment,
    FlagDiscussionReply,
    FlagDiscussionThread,
    UpdateDiscussionComment,
    UpdateDiscussionReply,
    UpdateDiscussionThread,
    UpvoteDiscussionComment,
    UpvoteDiscussionReply,
    UpvoteDiscussionThread,
    DownvoteDiscussionComment,
    DownvoteDiscussionReply,
    DownvoteDiscussionThread,
    Vote as VotePermission
)
from paper.models import Paper
from paper.utils import (
    get_cache_key,
    reset_cache,
    invalidate_top_rated_cache,
    invalidate_newest_cache,
    invalidate_most_discussed_cache,
)
from .utils import (
    get_comment_id_from_path,
    get_paper_id_from_path,
    get_thread_id_from_path
)

from utils import sentry
from reputation.models import Contribution
from reputation.tasks import create_contribution
from utils.permissions import CreateOrUpdateIfAllowed
from utils.siftscience import events_api, decisions_api, update_user_risk_score


class ActionMixin:
    """
    Note: Action decorators may be applied by classes inheriting this one.
    """

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            Endorse
            & CreateOrUpdateIfAllowed
        ]
    )
    def endorse(self, request, pk=None):
        item = self.get_object()
        user = request.user

        try:
            endorsement = create_endorsement(user, item)
            serialized = EndorsementSerializer(endorsement)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create endorsement: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    @endorse.mapping.delete
    def delete_endorse(self, request, pk=None):
        item = self.get_object()
        user = request.user
        try:
            endorsement = retrieve_endorsement(user, item)
            endorsement_id = endorsement.id
            endorsement.delete()
            return Response(endorsement_id, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete endorsement: {e}',
                status=400
            )

    def flag(self, request, pk=None):
        item = self.get_object()
        user = request.user
        reason = request.data.get('reason')

        try:
            flag = create_flag(user, item, reason)
            serialized = FlagSerializer(flag)

            content_id = f'{type(item).__name__}_{item.id}'
            events_api.track_flag_content(
                item.created_by,
                content_id,
                user.id
            )
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create flag: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    def delete_flag(self, request, pk=None):
        item = self.get_object()
        user = request.user
        try:
            flag = retrieve_flag(user, item)
            serialized = FlagSerializer(flag)
            flag.delete()
            return Response(serialized.data, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete flag: {e}',
                status=400
            )

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[
            IsAuthenticated,
            CensorDiscussion
        ]
    )
    def censor(self, request, pk=None):
        item = self.get_object()
        item.remove_nested()
        item.update_discussion_count()

        content_id = f'{type(item).__name__}_{item.id}'
        user = request.user
        content_creator = item.created_by
        events_api.track_flag_content(
            content_creator,
            content_id,
            user.id
        )
        decisions_api.apply_bad_content_decision(
            content_creator,
            content_id,
            'MANUAL_REVIEW',
            user
        )

        content_type = get_content_type_for_model(item)
        Contribution.objects.filter(
            content_type=content_type,
            object_id=item.id
        ).delete()
        return Response(
            self.get_serializer(instance=item).data,
            status=200
        )

    def upvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.UPVOTE)
        return response

    def downvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.DOWNVOTE)
        return response

    @action(detail=True, methods=['get'])
    def user_vote(self, request, pk=None):
        item = self.get_object()
        user = request.user
        vote = retrieve_vote(user, item)
        return get_vote_response(vote, 200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        try:
            item = self.get_object()
            user = request.user
            vote = retrieve_vote(user, item)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f'Failed to delete vote: {e}', status=400)

    def get_ordering(self):
        default_ordering = ['-score', 'created_date']

        ordering = self.request.query_params.get('ordering', default_ordering)
        if isinstance(ordering, str):
            if ordering and 'created_date' not in ordering:
                ordering = [ordering, 'created_date']
            elif 'created_date' not in ordering:
                ordering = ['created_date']
            else:
                ordering = [ordering]
        return ordering

    def get_action_context(self):

        ordering = self.get_ordering()
        needs_score = False
        if 'score' in ordering or '-score' in ordering:
            needs_score = True
        return {
            'ordering': ordering,
            'needs_score': needs_score,
        }

    def get_self_upvote_response(self, request, response, model):
        """Returns item in response data with upvote from creator and score."""
        item = model.objects.get(pk=response.data['id'])
        create_vote(request.user, item, Vote.UPVOTE)

        serializer = self.get_serializer(item)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def sift_track_create_content_comment(
        self,
        request,
        response,
        model,
        is_thread=False
    ):
        item = model.objects.get(pk=response.data['id'])
        tracked_comment = events_api.track_content_comment(
            item.created_by,
            item,
            request,
            is_thread=is_thread
        )
        update_user_risk_score(item.created_by, tracked_comment)

    def sift_track_update_content_comment(
        self,
        request,
        response,
        model,
        is_thread=False
    ):
        item = model.objects.get(pk=response.data['id'])
        tracked_comment = events_api.track_content_comment(
            item.created_by,
            item,
            request,
            is_thread=is_thread,
            update=True
        )
        update_user_risk_score(item.created_by, tracked_comment)


class ThreadViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = ThreadSerializer
    throttle_classes = THROTTLE_CLASSES

    # Optional attributes
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionThread
        & UpdateDiscussionThread
        & CreateOrUpdateIfAllowed
    ]
    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('-created_date',)

    def create(self, request, *args, **kwargs):
        paper_id = get_paper_id_from_path(request)
        paper = Paper.objects.get(id=paper_id)

        if request.query_params.get('created_location') == 'progress':
            request.data['created_location'] = (
                BaseComment.CREATED_LOCATION_PROGRESS
            )

        response = super().create(request, *args, **kwargs)
        response = self.get_self_upvote_response(request, response, Thread)
        self.sift_track_create_content_comment(
            request,
            response,
            Thread,
            is_thread=True
        )
        hubs = list(paper.hubs.values_list('id', flat=True))
        discussion_id = response.data['id']
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'thread'},
                request.user.id,
                paper_id,
                discussion_id
            ),
            priority=2,
            countdown=10
        )

        reset_cache([0])
        invalidate_top_rated_cache(hubs)
        invalidate_newest_cache(hubs)
        invalidate_most_discussed_cache(hubs)
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        self.sift_track_update_content_comment(
            request,
            response,
            Thread,
            is_thread=True
        )
        return response

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            **self.get_action_context(),
            'needs_score': True
        }

    def filter_queryset(self, *args, **kwargs):
        return super().filter_queryset(
            *args, **kwargs
        ).order_by(
            *self.get_ordering()
        )

    def get_queryset(self):
        upvotes = Count('votes', filter=Q(votes__vote_type=Vote.UPVOTE,))
        downvotes = Count('votes', filter=Q(votes__vote_type=Vote.DOWNVOTE,))
        paper_id = get_paper_id_from_path(self.request)
        source = self.request.query_params.get('source')
        is_removed = self.request.query_params.get('is_removed', False)
        if source and source == 'twitter':
            try:
                Paper.objects.get(
                    id=paper_id
                ).extract_twitter_comments(
                    use_celery=True
                )
            except Exception as e:
                sentry.log_error(e)

            threads = Thread.objects.filter(
                paper=paper_id,
                source=source
            )
        elif source == "researchhub":
            threads = Thread.objects.filter(
                paper=paper_id,
                source__in=[source, "inline_paper_body"]
            )
        elif source:
            threads = Thread.objects.filter(
                paper=paper_id,
                source=source
            )
        else:
            threads = Thread.objects.filter(
                paper=paper_id
            )

        threads = threads.filter(is_removed=is_removed)
        threads = threads.annotate(
            score=upvotes-downvotes
        )

        return threads.prefetch_related('paper')

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            FlagDiscussionThread
            & CreateOrUpdateIfAllowed
        ]
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            UpvoteDiscussionThread
            & VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            DownvoteDiscussionThread
            & VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


class CommentViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = CommentSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionComment
        & UpdateDiscussionComment
        & CreateOrUpdateIfAllowed
    ]

    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('created_date',)

    def get_queryset(self):
        thread_id = get_thread_id_from_path(self.request)
        is_removed = self.request.query_params.get('is_removed', False)

        comments = Comment.objects.filter(
            parent=thread_id,
            is_removed=is_removed
        ).order_by('-score', 'created_date')
        return comments

    def create(self, request, *args, **kwargs):
        paper_id = get_paper_id_from_path(request)
        paper = Paper.objects.get(id=paper_id)
        hubs = paper.hubs.values_list('id', flat=True)

        if request.query_params.get('created_location') == 'progress':
            request.data['created_location'] = (
                BaseComment.CREATED_LOCATION_PROGRESS
            )

        response = super().create(request, *args, **kwargs)
        response = self.get_self_upvote_response(request, response, Comment)
        discussion_id = response.data['id']
        self.sift_track_create_content_comment(request, response, Comment)

        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'comment'},
                request.user.id,
                paper_id,
                discussion_id
            ),
            priority=3,
            countdown=10
        )

        reset_cache([0])
        invalidate_top_rated_cache(hubs)
        invalidate_newest_cache(hubs)
        invalidate_most_discussed_cache(hubs)
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        self.sift_track_update_content_comment(request, response, Comment)
        return response

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            FlagDiscussionComment
            & CreateOrUpdateIfAllowed
        ]
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            UpvoteDiscussionComment
            & VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            DownvoteDiscussionComment
            & VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


class ReplyViewSet(viewsets.ModelViewSet, ActionMixin):
    serializer_class = ReplySerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionReply
        & UpdateDiscussionReply
        & CreateOrUpdateIfAllowed
    ]

    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    ordering = ('-created_date',)

    def get_queryset(self):
        comment_id = get_comment_id_from_path(self.request)
        is_removed = self.request.query_params.get('is_removed', False)
        comment = Comment.objects.first()
        replies = Reply.objects.filter(
            content_type=get_content_type_for_model(comment),
            object_id=comment_id,
            is_removed=is_removed
        )
        return replies

    def create(self, request, *args, **kwargs):
        paper_id = get_paper_id_from_path(request)

        if request.query_params.get('created_location') == 'progress':
            request.data['created_location'] = (
                BaseComment.CREATED_LOCATION_PROGRESS
            )

        response = super().create(request, *args, **kwargs)
        discussion_id = response.data['id']
        self.sift_track_create_content_comment(request, response, Reply)
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'reply'},
                request.user.id,
                paper_id,
                discussion_id
            ),
            priority=3,
            countdown=10
        )
        return self.get_self_upvote_response(request, response, Reply)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        self.sift_track_update_content_comment(request, response, Reply)
        return response

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            FlagDiscussionReply
            & CreateOrUpdateIfAllowed
        ]
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            UpvoteDiscussionReply
            & VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[
            DownvoteDiscussionReply
            & VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


def retrieve_endorsement(user, item):
    return Endorsement.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id
    )


def create_endorsement(user, item):
    endorsement = Endorsement(created_by=user, item=item)
    endorsement.save()
    return endorsement


def retrieve_flag(user, item):
    return Flag.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id
    )


def create_flag(user, item, reason):
    flag = Flag(created_by=user, item=item, reason=reason)
    flag.save()
    return flag


def find_vote(user, item, vote_type):
    vote = Vote.objects.filter(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def update_or_create_vote(request, user, item, vote_type):
    vote = retrieve_vote(user, item)

    if vote:
        vote.vote_type = vote_type
        vote.save(update_fields=['updated_date', 'vote_type'])
        events_api.track_content_vote(user, vote, request)
        return get_vote_response(vote, 200)

    vote = create_vote(user, item, vote_type)
    events_api.track_content_vote(user, vote, request)

    create_contribution.apply_async(
        (
            Contribution.UPVOTER,
            {'app_label': 'discussion', 'model': 'vote'},
            request.user.id,
            vote.paper.id,
            vote.id
        ),
        priority=2,
        countdown=10
    )
    return get_vote_response(vote, 201)


def get_vote_response(vote, status_code):
    serializer = VoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def retrieve_vote(user, item):
    try:
        return Vote.objects.get(
            object_id=item.id,
            content_type=get_content_type_for_model(item),
            created_by=user.id
        )
    except Vote.DoesNotExist:
        return None


def create_vote(user, item, vote_type):
    """Returns a vote of `voted_type` on `item` `created_by` `user`."""
    vote = Vote(created_by=user, item=item, vote_type=vote_type)
    vote.save()
    return vote


class CommentFileUpload(viewsets.ViewSet):
    permission_classes = [IsAuthenticated & CreateOrUpdateIfAllowed]
    throttle_classes = THROTTLE_CLASSES

    def create(self, request):
        _, base64_content = request.data.get('content').split(';base64,')
        base64_content = base64_content.encode()

        content_type = request.data.get('content_type')
        bucket_directory = f'comment_files/{content_type}'
        checksum = hashlib.md5(base64_content).hexdigest()
        path = f'{bucket_directory}/{checksum}.{content_type}'
        file_data = base64.b64decode(base64_content)
        data = ContentFile(file_data)

        if default_storage.exists(path):
            url = default_storage.url(path)
            res_status = status.HTTP_200_OK
        else:
            file_path = default_storage.save(path, data)
            url = default_storage.url(file_path)
            res_status = status.HTTP_201_CREATED

        url = url.split('?AWSAccessKeyId')[0]
        return Response(url, status=res_status)
