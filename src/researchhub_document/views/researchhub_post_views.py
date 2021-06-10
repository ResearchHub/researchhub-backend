from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated, AllowAny
)

from researchhub_document.models import ResearchhubPost
from researchhub_document.serializers.researchhub_post_serializer \
    import ResearchhubPostSerializer


class AuthorClaimCaseViewSet(ModelViewSet):
    permission_classes = [
        AllowAny,
    ]
    ordering = ('-created_date',)
    serializer_class = ResearchhubPostSerializer

    def get_queryset(self):
        query_params = self.request.query_params
        query_set = ResearchhubPost.objects.all()

        created_by_id = query_params.get('created_by')
        if (created_by_id is not None):
            query_set = query_set.filter()
        
        return query_set
