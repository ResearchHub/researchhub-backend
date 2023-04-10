from django.core.files.base import ContentFile
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.amplitude import track_event
from discussion.reaction_views import ReactionViewActionMixin
from hub.models import Hub
from hypothesis.models import Hypothesis
from hypothesis.serializers import DynamicCitationSerializer, HypothesisSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from researchhub_document.related_models.constants.document_type import HYPOTHESIS
from researchhub_document.related_models.constants.filters import NEW
from researchhub_document.utils import reset_unified_document_cache
from utils.throttles import THROTTLE_CLASSES


class HypothesisViewSet(ReactionViewActionMixin, ModelViewSet):
    ordering = "-created_date"
    queryset = Hypothesis.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly, HasDocumentEditingPermission]
    serializer_class = HypothesisSerializer
    throttle_classes = THROTTLE_CLASSES

    @track_event
    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        authors = data.get("authors", [])
        renderable_text = data.get("renderable_text", "")
        src = data.get("full_src", "")
        title = data.get("title", "")
        note_id = data.get("note_id", None)
        unified_doc = self._create_unified_doc(request)
        file_name, file = self._create_src_content_file(unified_doc, src, user)

        hypo = Hypothesis.objects.create(
            created_by=user,
            note_id=note_id,
            renderable_text=renderable_text,
            title=title,
            from_bounty_id=data.get("from_bounty", None),
            unified_document=unified_doc,
        )
        hypo.src.save(file_name, file)
        hypo.authors.set(authors)
        serializer = HypothesisSerializer(hypo)
        data = serializer.data

        hub_ids = unified_doc.hubs.values_list("id", flat=True)
        reset_unified_document_cache(
            hub_ids,
            document_type=["all", "hypothesis"],
            filters=[NEW],
            with_default_hub=True,
        )
        return Response(data, status=200)

    def _create_unified_doc(self, request):
        data = request.data
        hubs = Hub.objects.filter(id__in=data.get("hubs", [])).all()
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=HYPOTHESIS,
        )
        unified_doc.hubs.add(*hubs)
        unified_doc.save()
        return unified_doc

    @action(detail=True, methods=["post"])
    def upsert(self, request, *args, **kwargs):
        user = request.user
        data = request.data
        authors = data.pop("authors", None)
        hubs = data.pop("hubs", None)

        hypo = Hypothesis.objects.get(id=data.get("hypothesis_id"))
        unified_doc = hypo.unified_document
        serializer = HypothesisSerializer(hypo, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        file_name, full_src_file = self._create_src_content_file(
            unified_doc, request.data["full_src"], user
        )
        serializer.instance.src.save(file_name, full_src_file)

        if type(authors) is list:
            hypo.authors.set(authors)

        if type(hubs) is list:
            unified_doc = hypo.unified_document
            unified_doc.hubs.set(hubs)

        return Response(serializer.data, status=200)

    def _create_src_content_file(self, unified_doc, data, user):
        file_name = f"HYPOTHESIS-{unified_doc.id}--USER-{user.id}.txt"
        full_src_file = ContentFile(data.encode())
        return file_name, full_src_file

    @action(detail=True, methods=["get"])
    def get_citations(self, request, pk=None):
        citation_type = request.GET.get("citation_type")
        hypothesis = self.get_object()
        citations = hypothesis.citations.all().order_by("-vote_score")

        citation_set = (
            citations.filter(citation_type=citation_type)
            if citation_type
            else citations
        )

        context = self._get_citations_context()
        context["request"] = request

        serializer = DynamicCitationSerializer(
            citation_set,
            _include_fields=[
                "citation_type",
                "consensus_meta",
                "created_by",
                "created_date",
                "id",
                "inline_comment_count",
                "publish_date",
                "score",
                "source",
                "updated_date",
            ],
            many=True,
            context=context,
        )
        return Response(serializer.data, status=200)

    def _get_citations_context(self):
        context = {
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "hyp_dcs_get_created_by": {"_include_fields": ["id", "author_profile"]},
            "hyp_dcs_get_source": {
                "_include_fields": [
                    "id",
                    "documents",
                    "document_type",
                    "doi",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "created_date",
                    "doi",
                    "id",
                    "paper_title",
                    "slug",
                    "title",
                ]
            },
        }
        return context
