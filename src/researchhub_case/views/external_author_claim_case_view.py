from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from researchhub_case.constants.case_constants import EXTERNAL_AUTHOR_CLAIM
from researchhub_case.models import ExternalAuthorClaimCase
from researchhub_case.serializers import ExternalAuthorClaimCaseSerializer
from user.models import Action
from utils.http import POST
from utils.permissions import CreateOrReadOnly
from utils.semantic_scholar import SemanticScholar


class ExternalAuthorClaimCaseViewSet(ModelViewSet):
    # permission_classes = [IsAuthenticated, CreateOrReadOnly]
    permission_classes = [AllowAny]
    queryset = ExternalAuthorClaimCase.objects.all()
    serializer_class = ExternalAuthorClaimCaseSerializer
    semantic_scholar = SemanticScholar()

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        claim_data = {
            "case_type": EXTERNAL_AUTHOR_CLAIM,
            "requestor": user.id,
            "creator": user.id,
            **data,
        }
        serializer = self.get_serializer(data=claim_data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()

        Action.objects.create(item=obj, user=user, display=False)
        return Response(serializer.data, status=200)

    @action(
        detail=False,
        methods=[POST],
        # permission_classes=[IsAuthenticated],
    )
    def search_semantic_scholar_name(self, request):
        data = request.data
        name = data.get("name", "")
        semantic_scholar_data = self.semantic_scholar.get_authors(name)
        return Response(semantic_scholar_data, status=200)
