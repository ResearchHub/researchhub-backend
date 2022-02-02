import base64
import hashlib

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
    Reply,
    Thread,
    Vote,
)
from discussion.permissions import (
    CreateDiscussionComment,
    CreateDiscussionReply,
    CreateDiscussionThread,
    DownvoteDiscussionComment,
    DownvoteDiscussionReply,
    DownvoteDiscussionThread,
    FlagDiscussionComment,
    FlagDiscussionReply,
    FlagDiscussionThread,
    UpdateDiscussionComment,
    UpdateDiscussionReply,
    UpdateDiscussionThread,
    UpvoteDiscussionComment,
    UpvoteDiscussionReply,
    UpvoteDiscussionThread,
    Vote as VotePermission
)
from hypothesis.models import Hypothesis, Citation
from researchhub_document.models import ResearchhubPost
from researchhub_document.utils import reset_unified_document_cache
from paper.models import Paper
from paper.utils import (
    invalidate_most_discussed_cache,
    invalidate_newest_cache,
    invalidate_top_rated_cache,
)
from reputation.models import Contribution
from reputation.tasks import create_contribution
from utils import sentry
from utils.permissions import CreateOrUpdateIfAllowed
from .reaction_views import ReactionViewActionMixin
from .serializers import (
    CommentSerializer,
    ReplySerializer,
    ThreadSerializer,
)
from researchhub.lib import get_document_id_from_path
from .utils import (
    get_thread_id_from_path,
    get_comment_id_from_path,
)

DOCUMENT_MODELS = {
    'citation': Citation,
    'hypothesis': Hypothesis,
    'paper': Paper,
    'post': ResearchhubPost,
}


class ThreadViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
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
        document_type = request.path.split('/')[2]
        document_id = get_document_id_from_path(request)
        document = DOCUMENT_MODELS[document_type].objects.get(id=document_id)
        unified_document = document.unified_document if (
            document_type != 'citation'
        ) else document.source  # citation's unidoc is called "source"

        unified_doc_id = unified_document.id

        if request.query_params.get('created_location') == 'progress':
            request.data['created_location'] = (
                BaseComment.CREATED_LOCATION_PROGRESS
            )

        response = super().create(request, *args, **kwargs)
        response = self.get_self_upvote_response(request, response, Thread)
        hubs = list(unified_document.hubs.all().values_list('id', flat=True))
        discussion_id = response.data['id']

        self.sift_track_create_content_comment(
            request,
            response,
            Thread,
            is_thread=True
        )
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'thread'},
                request.user.id,
                unified_doc_id,
                discussion_id
            ),
            priority=2,
            countdown=10
        )
        reset_unified_document_cache([0])
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
        source = self.request.query_params.get('source')
        is_removed = self.request.query_params.get('is_removed', False)
        document_type = self.request.path.split('/')[2]

        if document_type == 'paper':
            paper_id = get_document_id_from_path(self.request)
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
                    source__in=[source, Thread.INLINE_PAPER_BODY]
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
        elif document_type == 'post':
            post_id = get_document_id_from_path(self.request)
            threads = Thread.objects.filter(
                post=post_id,
            )
        elif document_type == 'hypothesis':
            hypothesis_id = get_document_id_from_path(self.request)
            threads = Thread.objects.filter(
                hypothesis=hypothesis_id,
            )
        elif document_type == 'citation':
            citation_id = get_document_id_from_path(self.request)
            threads = Thread.objects.filter(
                citation=citation_id,
                source__in=[source, Thread.CITATION_COMMENT]
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


class CommentViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
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
        document_type = request.path.split('/')[2]
        document_id = get_document_id_from_path(request)
        document = DOCUMENT_MODELS[document_type].objects.get(id=document_id)
        unified_document = document.unified_document
        unified_doc_id = unified_document.id

        if request.query_params.get('created_location') == 'progress':
            request.data['created_location'] = (
                BaseComment.CREATED_LOCATION_PROGRESS
            )

        response = super().create(request, *args, **kwargs)
        response = self.get_self_upvote_response(request, response, Comment)
        hubs = list(unified_document.hubs.all().values_list('id', flat=True))
        self.sift_track_create_content_comment(request, response, Comment)

        discussion_id = response.data['id']
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'comment'},
                request.user.id,
                unified_doc_id,
                discussion_id
            ),
            priority=3,
            countdown=10
        )
        reset_unified_document_cache([0])
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


class ReplyViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
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
        document_type = request.path.split('/')[2]
        document_id = get_document_id_from_path(request)
        document = DOCUMENT_MODELS[document_type].objects.get(id=document_id)
        unified_document = document.unified_document
        unified_doc_id = unified_document.id

        if request.query_params.get('created_location') == 'progress':
            request.data['created_location'] = (
                BaseComment.CREATED_LOCATION_PROGRESS
            )

        response = super().create(request, *args, **kwargs)
        hubs = list(unified_document.hubs.all().values_list('id', flat=True))
        self.sift_track_create_content_comment(request, response, Reply)

        discussion_id = response.data['id']
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {'app_label': 'discussion', 'model': 'reply'},
                request.user.id,
                unified_doc_id,
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


# TODO: https://www.notion.so/researchhub/Make-a-generic-class-to-handle-uploading-files-to-S3-88c40abfbbe04a03aa00f82f9ab7c345
class CommentFileUpload(viewsets.ViewSet):
    permission_classes = [IsAuthenticated & CreateOrUpdateIfAllowed]
    throttle_classes = THROTTLE_CLASSES
    ALLOWED_EXTENSIONS = (
        'gif',
        'jpeg',
        'pdf',
        'png',
        'svg',
        'tiff',
        'webp',
    )

    def create(self, request):
        if request.FILES:
            data = request.FILES['upload']
            content_type = data.content_type.split('/')[1]

            # Extension check
            if content_type.lower() not in self.ALLOWED_EXTENSIONS:
                return Response('Invalid extension', status=400)

            # Special characters check
            if any(not c.isalnum() for c in content_type):
                return Response(status=400)

            content = data.read()
            bucket_directory = f'comment_files/{content_type}'
            checksum = hashlib.md5(content).hexdigest()
            path = f'{bucket_directory}/{checksum}.{content_type}'

            if default_storage.exists(path):
                url = default_storage.url(path)
                res_status = status.HTTP_200_OK
            else:
                file_path = default_storage.save(path, data)
                url = default_storage.url(file_path)
                res_status = status.HTTP_201_CREATED

            url = url.split('?AWSAccessKeyId')[0]
            return Response({'url': url}, status=res_status)
        else:
            content_type = request.data.get('content_type')
            if content_type.lower() not in self.ALLOWED_EXTENSIONS:
                return Response(status=400)

            if any(not c.isalnum() for c in content_type):
                return Response(status=400)

            _, base64_content = request.data.get('content').split(';base64,')
            base64_content = base64_content.encode()

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
