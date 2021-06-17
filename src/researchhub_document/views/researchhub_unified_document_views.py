import datetime

from django.db.models import (
    Q,
    Count
)
from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated
)

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.serializers import (
  ResearchhubUnifiedDocumentSerializer
)
from researchhub_document.related_models.constants.document_type import (
    DOCUMENT_TYPES
)


class ResearchhubUnifiedDocumentViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    queryset = ResearchhubUnifiedDocument.objects
    serializer_class = ResearchhubUnifiedDocumentSerializer

    def _get_document_filtering(self, query_params):
        filtering = query_params.get('filter', None)
        if filtering == 'removed':
            filtering = 'removed'
        elif filtering == 'top_rated':
            filtering = '-score'
        elif filtering == 'most_discussed':
            filtering = '-discussed'
        elif filtering == 'newest':
            filtering = '-created_date'
        elif filtering == 'hot':
            filtering = '-hot_score'
        elif filtering == 'user_uploaded':
            filtering = 'user_uploaded'
        else:
            filtering = '-score'
        return filtering

    def get_filtered_queryset(
        self,
        document_type,
        filtering,
        start_date,
        end_date
    ):
        if document_type == 'paper':
            qs = self.queryset.filter(
                document_type=DOCUMENT_TYPES.PAPER
            )
        elif document_type == 'posts':
            qs = self.queryset.filter(
                document_type=(
                    Q(document_type=DOCUMENT_TYPES.ELN) |
                    Q(document_type=DOCUMENT_TYPES.DISCUSSION)
                )
            )
        else:
            qs = self.queryset.all()

        qs = qs.filter(
            created_date__gte=start_date,
            created_date__lte=end_date
        )

        if filtering == 'removed':
            qs = qs.filter(
                is_removed=True
            ).order_by(
                '-created_date'
            )
        elif filtering == '-score':
            qs = qs.order_by(filtering)
        elif filtering == '-discussed':
            paper_threads_count = Count('paper__threads')
            paper_comments_count = Count('paper__threads__comments')
            posts_threads__count = Count('posts__threads')
            posts_comments_count = Count('posts__threads__comments')
            qs = qs.filter(
                (
                    Q(paper__threads__isnull=False) |
                    Q(posts__threads__isnull=False)
                )
            ).annotate(
                discussed=(
                    paper_threads_count +
                    paper_comments_count +
                    posts_threads__count +
                    posts_comments_count
                )
            ).order_by(
                '-discussed'
            )
        elif filtering == '-created_date':
            qs = qs.order_by(filtering)
        elif filtering == '-hot_score':
            qs = qs.order_by(filtering)
        elif filtering == 'user_uploaded':
            qs = qs.filter(
                (
                    Q(paper__uploaded_by__isnull=False) |
                    Q(posts__created_by__isnull=False)
                )
            ).order_by(
                '-created_date'
            )
        else:
            qs = qs.order_by('-hot_score')

        return qs

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[AllowAny]
    )
    def get_unified_documents(self, request):
        query_params = request.query_params
        document_request_type = query_params.get('type', 'all')
        start_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('start_date__gte', 0)),
            datetime.timezone.utc
        )
        end_date = datetime.datetime.fromtimestamp(
            int(request.GET.get('end_date__lte', 0)),
            datetime.timezone.utc
        )
        filtering = self._get_document_filtering(query_params)
        documents = self.get_filtered_queryset(
            document_request_type,
            filtering,
            start_date,
            end_date
        )
        page = self.paginate_queryset(documents)
        serializer = self.serializer_class(page, many=True)
        serializer_data = serializer.data

        return self.get_paginated_response(serializer_data)
