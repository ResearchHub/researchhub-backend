import datetime

from django.db.models import (
    Q,
    Count
)
from django.core.files.base import ContentFile
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action

from hub.models import Hub
from discussion.reaction_views import ReactionViewActionMixin
from researchhub_document.related_models.constants.document_type \
    import DISCUSSION
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from researchhub_document.related_models.constants.document_type import (
    DOCUMENT_TYPES
)
from researchhub_document.models import (
    ResearchhubPost, ResearchhubUnifiedDocument
)
from researchhub_document.serializers.researchhub_post_serializer \
    import ResearchhubPostSerializer
from user.models import User


class ResearchhubPostViewSet(ModelViewSet, ReactionViewActionMixin):
    ordering = ('-created_date')
    queryset = ResearchhubUnifiedDocument.objects
    permission_classes = [AllowAny]  # change to IsAuthenticated
    serializer_class = ResearchhubPostSerializer

    def create(self, request, *args, **kwargs):
        # TODO: calvinhlee - relocation below function to model/signal
        return self.upsert_researchhub_posts(request)

    def update(self, request, *args, **kwargs):
        # TODO: calvinhlee - relocation below function to model/signal
        return self.upsert_researchhub_posts(request)

    def get_queryset(self):
        request = self.request
        try:
            query_set = ResearchhubPost.objects.all()
            query_params = request.query_params
            created_by_id = query_params.get('created_by')
            post_id = query_params.get('post_id')
            if (created_by_id is not None):
                query_set = query_set.filter(created_by__id=created_by_id)
            if (post_id is not None):
                query_set = query_set.filter(id=post_id)
            return query_set.order_by('-created_date')
        except (KeyError, TypeError) as exception:
            return Response(exception, status=400)

    def upsert_researchhub_posts(self, request):
        try:
            request_data = request.data
            prev_version_id = request_data.get('prev_version_id')
            if (prev_version_id is not None):
                return self.update_existing_researchhub_posts(request)
            else:
                return self.create_researchhub_post(request)
        except (KeyError, TypeError) as exception:
            return Response(exception, status=400)

    def create_researchhub_post(self, request):
        try:
            request_data = request.data
            document_type = request_data.get('document_type')
            created_by_user = User.objects.get(
                id=request_data.get('created_by')
            )
            is_discussion = document_type == DISCUSSION
            editor_type = request_data.get('editor_type')

            # logical ordering & not using signals to avoid race-conditions
            access_group = self.create_access_group(request)
            unified_document = self.create_unified_doc(request)
            if (access_group is not None):
                unified_document.access_group = access_group
                unified_document.save()

            rh_post = ResearchhubPost.objects.create(
                created_by=created_by_user,
                document_type=document_type,
                editor_type=CK_EDITOR if editor_type is None else editor_type,
                prev_version=None,
                preview_img=request_data.get('preview_img'),
                renderable_text=request_data.get('renderable_text'),
                title=request_data.get('title'),
                unified_document=unified_document,
            )
            file_name = "RH-POST-{doc_type}-USER-{user_id}.txt".format(
                doc_type=document_type,
                user_id=created_by_user.id
            )
            full_src_file = ContentFile(request_data['full_src'].encode())
            if is_discussion:
                rh_post.discussion_src.save(file_name, full_src_file)
            else:
                rh_post.eln_src.save(file_name, full_src_file)

            return Response(
                ResearchhubPostSerializer(
                    ResearchhubPost.objects.get(id=rh_post.id)
                ).data,
                status=200
            )

        except (KeyError, TypeError) as exception:
            print("EXCEPTION: ", exception)
            return Response(exception, status=400)

    def update_existing_researchhub_posts(self, request):
        return Response("Update currently not supported", status=400)

    def create_access_group(self, request):
        # TODO: calvinhlee - access group is for ELN
        return None

    def create_unified_doc(self, request):
        try:
            request_data = request.data
            hubs = Hub.objects.filter(
                id__in=request_data.get('hubs')
            ).all()
            uni_doc = ResearchhubUnifiedDocument.objects.create(
                document_type=request_data.get('document_type'),
            )
            uni_doc.hubs.add(*hubs)
            uni_doc.save()
            return uni_doc
        except (KeyError, TypeError) as exception:
            print("create_unified_doc: ", exception)

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
            qs = self.queryset

        qs = qs.filter(created_date__gte=start_date, created_date_lte=end_date)

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
            return qs.order_by('-hot_score')

    @action(
        detail=False,
        methods=['get'],
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
