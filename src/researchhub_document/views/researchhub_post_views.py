from django.core.files.base import ContentFile
from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated, AllowAny
)

from hub.models import Hub
from researchhub_document.related_models.constants.document_type \
    import DISCUSSION
from researchhub_document.models import ResearchhubPost
from researchhub_document.serializers.researchhub_post_serializer \
    import ResearchhubPostSerializer
from user.models import User


class AuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [
        AllowAny,
    ]
    ordering = ('-created_date',)
    serializer_class = ResearchhubPostSerializer

    def get_queryset(self, prefetch=True):
        query_params = self.request.query_params
        query_set = ResearchhubPost.objects.all()

        created_by_id = query_params.get('created_by')
        if (created_by_id is not None):
            query_set = query_set.filter()
        
        return query_set

    @action(
        detail=True,
        methods=['get', 'post', 'put'],
    )
    def post_create(self, request, pk='post_create'):
        print("HEYYYYYY")
        request_data = request.data
        created_by_user = User.objects.filter(
            id=request_data.get('created_by_id')
        ).first()
        prev_version = ResearchhubPost.objects.filter(
            id=request_data.get('prev_version_id')
        ).first()
        hubs = Hub.objects.filter(
          id__in=request_data['hub_ids']
        )
        full_src_file = ContentFile(request_data['full_src'])
        is_discussion = request.data.get('document_type') == DISCUSSION

        return ResearchhubPost.create(
            # **validated_data,
            created_by=created_by_user,
            discussion_src=full_src_file if is_discussion else None,
            eln_src=full_src_file if not is_discussion else None,
            hubs=hubs,
            prev_version=prev_version,
        )
