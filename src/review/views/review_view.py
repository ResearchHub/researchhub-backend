from rest_framework.response import Response
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
)
from rest_framework.decorators import action
from discussion.models import Thread
from discussion.reaction_views import ReactionViewActionMixin
from discussion.services.thread_service import update_thread
from review.models.review_model import Review
from utils.sentry import log_error
from discussion.serializers import ThreadSerializer
from review.permissions import (
    CreateReview,
    UpdateReview,
)
from review.serializers import ReviewSerializer
from utils.throttles import THROTTLE_CLASSES
from rest_framework.filters import OrderingFilter
from researchhub_document.models import (
    ResearchhubUnifiedDocument,
)
from discussion.services import create_thread
from review.services import create_review
from researchhub_document.utils import (
    get_doc_type_key,
    reset_unified_document_cache,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    TRENDING,
)

class ReviewViewSet(viewsets.ModelViewSet, ReactionViewActionMixin):
    serializer_class = ReviewSerializer
    throttle_classes = THROTTLE_CLASSES

    permission_classes = [
        IsAuthenticatedOrReadOnly
        & CreateReview
        & UpdateReview
    ]
    filter_backends = (OrderingFilter,)
    order_fields = '__all__'
    queryset = Review.objects.all()
    ordering = ('-created_date',)

    @action(
        detail=False,
        methods=['post'],
    )
    def create_review(self, request,pk=None):
        unified_document = ResearchhubUnifiedDocument.objects.get(id=pk)
        has_discussion = request.data.get('discussion', False)

        try:
            with transaction.atomic():
                review = create_review(
                    data=request.data['review'],
                    unified_document=unified_document,
                    context={'request': request}
                )

                thread = None
                if has_discussion:
                    thread = create_thread(
                        data=request.data['discussion'],
                        user=request.user,
                        for_model=unified_document.get_document().__class__.__name__,
                        for_model_id=unified_document.get_document().id,
                        context={'request': request}
                    )

                    thread.review = review
                    thread.save()

        except Exception as error:
            message = "Failed to create review"
            log_error(error, message)
            return Response(
                message,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = Response({
            'thread': ThreadSerializer(thread).data,
            'review': ReviewSerializer(review).data
        },
            status=status.HTTP_201_CREATED,
        )

        if has_discussion:
            doc_type = get_doc_type_key(thread.unified_document)
            hubs = list(thread.unified_document.hubs.all().values_list('id', flat=True))
            
            reset_unified_document_cache(
                hub_ids=hubs,
                document_type=[doc_type, 'all'],
                filters=[DISCUSSED, TRENDING],
            )

            self.sift_track_create_content_comment(
                request,
                response.data['thread'],
                Thread,
                is_thread=True
            )
        
        return response

    @action(
        detail=True,
        methods=['put', 'patch'],
    )
    def update_review(self, request, *args, **kwargs):
        pass
        # review = Review.objects.get(id=kwargs['pk'])
        # thread = Thread.objects.get(review=Review)
        # print('review', review)
        # print('thread', thread)

        # if request.data.get('discussion'):
        #     thread = update_thread(
        #         data=request.data['discussion'],
        #         context={'request': request}
        #     )
        # if request.data.get('review'):
        #     pass
        #     # update_thread(data=request.data, context={'request': request})

        # response = Response({
        #     'thread': ThreadSerializer(thread).data,
        #     # 'review': ReviewSerializer(review).data
        # },
        #     status=status.HTTP_200_OK,
        # )

        # return response
