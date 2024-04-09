import base64
import hashlib

from django.contrib.admin.options import get_content_type_for_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from analytics.amplitude import track_event
from discussion.models import BaseComment, Comment, Reply, Thread
from discussion.permissions import (
    CanGiveCommentBounty,
    CensorComment,
    CensorReply,
    CensorThread,
    CreateDiscussionComment,
    CreateDiscussionReply,
    CreateDiscussionThread,
    DownvoteDiscussionComment,
    DownvoteDiscussionReply,
    DownvoteDiscussionThread,
    FlagDiscussionComment,
    FlagDiscussionReply,
    FlagDiscussionThread,
    IsOriginalQuestionPoster,
    UpdateDiscussionComment,
    UpdateDiscussionReply,
    UpdateDiscussionThread,
    UpvoteDiscussionComment,
    UpvoteDiscussionReply,
    UpvoteDiscussionThread,
)
from discussion.permissions import Vote as VotePermission
from hypothesis.models import Citation, Hypothesis
from paper.models import Paper
from peer_review.models import PeerReview
from reputation.models import Contribution
from reputation.tasks import create_contribution
from researchhub.lib import get_document_id_from_path
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    FILTER_ANSWERED,
    FILTER_BOUNTY_CLOSED,
    FILTER_BOUNTY_OPEN,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
    SORT_DISCUSSED,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    EXPIRING_SOON,
    HOT,
    MOST_RSC,
)
from researchhub_document.utils import get_doc_type_key, reset_unified_document_cache
from utils import sentry
from utils.permissions import CreateOrUpdateIfAllowed
from utils.throttles import THROTTLE_CLASSES

from .reaction_views import ReactionViewActionMixin
from .serializers import (
    CommentSerializer,
    DynamicThreadSerializer,
    ReplySerializer,
    ThreadSerializer,
)
from .utils import (
    ORDERING_SCORE_ANNOTATION,
    get_comment_id_from_path,
    get_reply_id_from_path,
    get_thread_id_from_path,
)

RELATED_DISCUSSION_MODELS = {
    "citation": Citation,
    "hypothesis": Hypothesis,
    "paper": Paper,
    "peer_review": PeerReview,
    "researchhub_post": ResearchhubPost,
}


class ThreadViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
    serializer_class = ThreadSerializer
    dynamic_serializer_class = DynamicThreadSerializer
    throttle_classes = THROTTLE_CLASSES

    # Optional attributes
    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateDiscussionThread
        & UpdateDiscussionThread
        & CreateOrUpdateIfAllowed
    ]
    filter_backends = (OrderingFilter,)
    order_fields = "__all__"

    @track_event
    def create(self, request, *args, **kwargs):
        model = request.path.split("/")[2]
        model_id = get_document_id_from_path(request)
        instance = RELATED_DISCUSSION_MODELS[model].objects.get(id=model_id)

        if model == "citation":
            unified_document = instance.source
        else:
            unified_document = instance.unified_document

        if request.query_params.get("created_location") == "progress":
            request.data["created_location"] = BaseComment.CREATED_LOCATION_PROGRESS
        response = super().create(request, *args, **kwargs)
        response = self.get_self_upvote_response(request, response, Thread)

        created_thread = Thread.objects.get(id=response.data["id"])
        if request.data.get("review"):
            created_thread.review_id = request.data.get("review")
            created_thread.save()

        unified_document.update_filter(SORT_DISCUSSED)
        discussion_id = response.data["id"]

        self.sift_track_create_content_comment(
            request, response, Thread, is_thread=True
        )
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {"app_label": "discussion", "model": "thread"},
                request.user.id,
                unified_document.id,
                discussion_id,
            ),
            priority=1,
            countdown=10,
        )

        doc_type = get_doc_type_key(unified_document)
        reset_unified_document_cache(
            document_type=[doc_type, "all"],
            filters=[DISCUSSED, HOT],
        )

        return Response(
            self.serializer_class(created_thread).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        self.sift_track_update_content_comment(
            request, response, Thread, is_thread=True
        )
        return response

    @action(
        detail=True,
        methods=["patch", "delete"],
        permission_classes=[CensorThread],
    )
    def delete(self, request, *args, **kwargs):
        thread_id = get_thread_id_from_path(self.request)

        instance = Thread.objects.get(id=thread_id)
        instance.is_removed = True
        action = instance.actions
        if action.exists():
            action = action.first()
            action.is_removed = True
            action.save()

        instance.save()

        review = instance.review
        if review:
            review.is_removed = True
            review.save()

        return Response(status=status.HTTP_200_OK)

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            **self.get_action_context(),
            "needs_score": True,
        }

    def get_queryset(self):
        source = self.request.query_params.get("source")
        is_removed = self.request.query_params.get("is_removed", "false").lower()
        is_removed = False if is_removed == "false" else True
        document_type = self.request.path.split("/")[2]

        order = ["-ordering_score", "created_date"]
        if document_type == "paper":
            paper_id = get_document_id_from_path(self.request)
            if source == "researchhub":
                threads = Thread.objects.filter(
                    paper=paper_id, source__in=[source, Thread.INLINE_PAPER_BODY]
                )
            elif source:
                threads = Thread.objects.filter(paper=paper_id, source=source)
            else:
                threads = Thread.objects.filter(paper=paper_id)
        elif document_type == "researchhub_post":
            post_id = get_document_id_from_path(self.request)
            threads = Thread.objects.filter(
                post=post_id,
            )
            order.insert(0, "is_accepted_answer")
        elif document_type == "hypothesis":
            hypothesis_id = get_document_id_from_path(self.request)
            threads = Thread.objects.filter(
                Q(hypothesis=hypothesis_id)
                | Q(
                    citation_id__in=Citation.objects.filter(
                        hypothesis=hypothesis_id
                    ).values_list("id", flat=True)
                )
            )
        elif document_type == "citation":
            citation_id = get_document_id_from_path(self.request)
            threads = Thread.objects.filter(
                citation=citation_id, source__in=[source, Thread.CITATION_COMMENT]
            )
        threads = (
            threads.filter(is_removed=is_removed)
            .filter(created_by__isnull=False)
            .annotate(
                ordering_score=ORDERING_SCORE_ANNOTATION,
            )
            .order_by(*order)
        )
        return threads.prefetch_related("paper")

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[FlagDiscussionThread & CreateOrUpdateIfAllowed],
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=["post", "put", "patch"],
        permission_classes=[
            UpvoteDiscussionThread & VotePermission & CreateOrUpdateIfAllowed
        ],
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=["post", "put", "patch"],
        permission_classes=[
            DownvoteDiscussionThread & VotePermission & CreateOrUpdateIfAllowed
        ],
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsOriginalQuestionPoster],
    )
    def mark_as_accepted_answer(self, *args, **kwargs):
        # try:
        document_id = get_document_id_from_path(self.request)
        target_post_question = ResearchhubPost.objects.get(id=document_id)

        # logical ordering - DO NOT CHANGE THE ORDER OF OPERATIONS
        prev_accepted_answer = target_post_question.get_accepted_answer()
        target_thread = self.get_object()

        if prev_accepted_answer is not None:
            prev_accepted_answer.is_accepted_answer = False
            prev_accepted_answer.save()

        target_thread.is_accepted_answer = True
        target_thread.save()

        target_thread.unified_document.update_filters(
            (
                FILTER_ANSWERED,
                SORT_BOUNTY_TOTAL_AMOUNT,
                SORT_BOUNTY_EXPIRATION_DATE,
                FILTER_BOUNTY_CLOSED,
                FILTER_BOUNTY_OPEN,
            )
        )
        unified_document = target_thread.unified_document
        doc_type = get_doc_type_key(unified_document)
        reset_unified_document_cache(
            document_type=[doc_type],
            filters=[EXPIRING_SOON, MOST_RSC],
        )
        return Response({"thread_id": target_thread.id}, status=200)
        # except Exception as exception:
        #     return Response(str(exception), status=400)


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
    order_fields = "__all__"
    ordering = ("-created_date",)

    def get_queryset(self):
        thread_id = get_thread_id_from_path(self.request)
        is_removed = self.request.query_params.get("is_removed", False)

        comments = (
            Comment.objects.filter(parent=thread_id, is_removed=is_removed)
            .filter(created_by__isnull=False)
            .annotate(ordering_score=ORDERING_SCORE_ANNOTATION)
            .order_by("-ordering_score", "created_date")
        )
        return comments

    @track_event
    def create(self, request, *args, **kwargs):
        document_type = request.path.split("/")[2]
        document_id = get_document_id_from_path(request)
        document = RELATED_DISCUSSION_MODELS[document_type].objects.get(id=document_id)
        unified_document = document.unified_document
        unified_doc_id = unified_document.id

        if request.query_params.get("created_location") == "progress":
            request.data["created_location"] = BaseComment.CREATED_LOCATION_PROGRESS
        response = super().create(request, *args, **kwargs)
        response = self.get_self_upvote_response(request, response, Comment)
        unified_document.update_filter(SORT_DISCUSSED)
        self.sift_track_create_content_comment(request, response, Comment)

        discussion_id = response.data["id"]
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {"app_label": "discussion", "model": "comment"},
                request.user.id,
                unified_doc_id,
                discussion_id,
            ),
            priority=3,
            countdown=10,
        )

        doc_type = get_doc_type_key(unified_document)
        reset_unified_document_cache(
            document_type=[doc_type, "all"],
            filters=[DISCUSSED, HOT],
        )

        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        self.sift_track_update_content_comment(request, response, Comment)
        return response

    @action(
        detail=True,
        methods=["patch", "delete"],
        permission_classes=[CensorComment],
    )
    def delete(self, request, *args, **kwargs):
        comment_id = get_comment_id_from_path(self.request)

        instance = Comment.objects.get(id=comment_id)
        instance.is_removed = True
        action = instance.actions
        if action.exists():
            action = action.first()
            action.is_removed = True
            action.save()
        instance.save()

        return Response(status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[CanGiveCommentBounty],
    )
    def mark_as_accepted_answer(self, *args, **kwargs):
        comment = self.get_object()
        thread = comment.parent

        # logical ordering - DO NOT CHANGE THE ORDER OF OPERATIONS
        prev_accepted_answer = thread.get_accepted_answer()

        if prev_accepted_answer is not None:
            prev_accepted_answer.is_accepted_answer = False
            prev_accepted_answer.save()

        comment.is_accepted_answer = True
        comment.save()

        comment.unified_document.update_filters(
            (
                FILTER_ANSWERED,
                SORT_BOUNTY_TOTAL_AMOUNT,
                SORT_BOUNTY_EXPIRATION_DATE,
                FILTER_BOUNTY_CLOSED,
                FILTER_BOUNTY_OPEN,
            )
        )
        unified_document = comment.unified_document
        doc_type = get_doc_type_key(unified_document)
        reset_unified_document_cache(
            document_type=[doc_type],
            filters=[EXPIRING_SOON, MOST_RSC],
        )
        return Response({"comment_id": comment.id}, status=200)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[FlagDiscussionComment & CreateOrUpdateIfAllowed],
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=["post", "put", "patch"],
        permission_classes=[
            UpvoteDiscussionComment & VotePermission & CreateOrUpdateIfAllowed
        ],
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=["post", "put", "patch"],
        permission_classes=[
            DownvoteDiscussionComment & VotePermission & CreateOrUpdateIfAllowed
        ],
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
    order_fields = "__all__"
    ordering = ("-created_date",)

    def get_queryset(self):
        comment_id = get_comment_id_from_path(self.request)
        is_removed = self.request.query_params.get("is_removed", False)
        comment = Comment.objects.first()
        replies = (
            Reply.objects.filter(
                content_type=get_content_type_for_model(comment),
                object_id=comment_id,
                is_removed=is_removed,
            )
            .filter(created_by__isnull=False)
            .annotate(ordering_score=ORDERING_SCORE_ANNOTATION)
            .order_by("-ordering_score", "created_date")
        )

        return replies

    @track_event
    def create(self, request, *args, **kwargs):
        document_type = request.path.split("/")[2]
        document_id = get_document_id_from_path(request)
        document = RELATED_DISCUSSION_MODELS[document_type].objects.get(id=document_id)
        unified_document = document.unified_document
        unified_doc_id = unified_document.id

        if request.query_params.get("created_location") == "progress":
            request.data["created_location"] = BaseComment.CREATED_LOCATION_PROGRESS

        response = super().create(request, *args, **kwargs)
        unified_document.update_filter(SORT_DISCUSSED)
        self.sift_track_create_content_comment(request, response, Reply)

        discussion_id = response.data["id"]
        create_contribution.apply_async(
            (
                Contribution.COMMENTER,
                {"app_label": "discussion", "model": "reply"},
                request.user.id,
                unified_doc_id,
                discussion_id,
            ),
            priority=3,
            countdown=10,
        )

        doc_type = get_doc_type_key(unified_document)
        reset_unified_document_cache(
            document_type=[doc_type, "all"],
            filters=[DISCUSSED, HOT],
        )

        return self.get_self_upvote_response(request, response, Reply)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        self.sift_track_update_content_comment(request, response, Reply)
        return response

    @action(
        detail=True,
        methods=["patch", "delete"],
        permission_classes=[CensorReply],
    )
    def delete(self, request, *args, **kwargs):
        reply_id = get_reply_id_from_path(self.request)

        instance = Reply.objects.get(id=reply_id)
        instance.is_removed = True
        action = instance.actions
        if action.exists():
            action = action.first()
            action.is_removed = True
            action.save()
        instance.save()

        return Response(status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[FlagDiscussionReply & CreateOrUpdateIfAllowed],
    )
    def flag(self, *args, **kwargs):
        return super().flag(*args, **kwargs)

    @flag.mapping.delete
    def delete_flag(self, *args, **kwargs):
        return super().delete_flag(*args, **kwargs)

    @action(
        detail=True,
        methods=["post", "put", "patch"],
        permission_classes=[
            UpvoteDiscussionReply & VotePermission & CreateOrUpdateIfAllowed
        ],
    )
    def upvote(self, *args, **kwargs):
        return super().upvote(*args, **kwargs)

    @action(
        detail=True,
        methods=["post", "put", "patch"],
        permission_classes=[
            DownvoteDiscussionReply & VotePermission & CreateOrUpdateIfAllowed
        ],
    )
    def downvote(self, *args, **kwargs):
        return super().downvote(*args, **kwargs)


# TODO: https://www.notion.so/researchhub/Make-a-generic-class-to-handle-uploading-files-to-S3-88c40abfbbe04a03aa00f82f9ab7c345
class CommentFileUpload(viewsets.ViewSet):
    permission_classes = [IsAuthenticated & CreateOrUpdateIfAllowed]
    ALLOWED_EXTENSIONS = (
        "gif",
        "jpeg",
        "pdf",
        "png",
        "svg",
        "tiff",
        "webp",
        "mp4",
        "webm",
        "ogg",
    )

    def create(self, request):
        if request.FILES:
            data = request.FILES["upload"]
            content_type = data.content_type.split("/")[1]

            # Extension check
            if content_type.lower() not in self.ALLOWED_EXTENSIONS:
                return Response("Invalid extension", status=400)

            # Special characters check
            if any(not c.isalnum() for c in content_type):
                return Response("Special Characters", status=400)

            content = data.read()
            bucket_directory = f"comment_files/{content_type}"
            checksum = hashlib.md5(content).hexdigest()
            path = f"{bucket_directory}/{checksum}.{content_type}"

            if default_storage.exists(path):
                url = default_storage.url(path)
                res_status = status.HTTP_200_OK
            else:
                file_path = default_storage.save(path, data)
                url = default_storage.url(file_path)
                res_status = status.HTTP_201_CREATED

            url = url.split("?AWSAccessKeyId")[0]
            return Response({"url": url}, status=res_status)
        else:
            content_type = request.data.get("content_type")
            if content_type.lower() not in self.ALLOWED_EXTENSIONS:
                return Response("Invalid extension", status=400)

            if any(not c.isalnum() for c in content_type):
                return Response("Special Characters", status=400)

            _, base64_content = request.data.get("content").split(";base64,")
            base64_content = base64_content.encode()

            bucket_directory = f"comment_files/{content_type}"
            checksum = hashlib.md5(base64_content).hexdigest()
            path = f"{bucket_directory}/{checksum}.{content_type}"
            file_data = base64.b64decode(base64_content)
            data = ContentFile(file_data)

            if default_storage.exists(path):
                url = default_storage.url(path)
                res_status = status.HTTP_200_OK
            else:
                file_path = default_storage.save(path, data)
                url = default_storage.url(file_path)
                res_status = status.HTTP_201_CREATED

            url = url.split("?AWSAccessKeyId")[0]
            return Response(url, status=res_status)
