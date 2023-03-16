import random
import string
import time
from datetime import datetime

import requests
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from analytics.amplitude import track_event
from discussion.reaction_views import ReactionViewActionMixin
from hub.models import Hub
from note.models import NoteContent
from peer_review.serializers import PeerReviewRequestSerializer
from purchase.models import Balance, Purchase
from researchhub.settings import (
    BASE_FRONTEND_URL,
    CROSSREF_API_URL,
    CROSSREF_DOI_PREFIX,
    CROSSREF_DOI_RSC_FEE,
    CROSSREF_DOI_SUFFIX_LENGTH,
    CROSSREF_LOGIN_ID,
    CROSSREF_LOGIN_PASSWORD,
    TESTING,
)
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.permissions import HasDocumentEditingPermission
from researchhub_document.related_models.constants.document_type import (
    ALL,
    BOUNTY,
    POSTS,
    QUESTION,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    HOT,
    MOST_RSC,
    NEW,
    UPVOTED,
)
from researchhub_document.serializers.researchhub_post_serializer import (
    ResearchhubPostSerializer,
)
from researchhub_document.utils import reset_unified_document_cache
from utils.sentry import log_error


class ResearchhubPostViewSet(ReactionViewActionMixin, ModelViewSet):
    ordering = "-created_date"
    queryset = ResearchhubUnifiedDocument.objects.all()
    permission_classes = [AllowAny, HasDocumentEditingPermission]
    serializer_class = ResearchhubPostSerializer

    @track_event
    def create(self, request, *args, **kwargs):
        return self.upsert_researchhub_posts(request)

    def update(self, request, *args, **kwargs):
        return self.upsert_researchhub_posts(request)

    def get_queryset(self):
        request = self.request
        try:
            query_set = ResearchhubPost.objects.all()
            query_params = request.query_params
            created_by_id = query_params.get("created_by")
            post_id = query_params.get("post_id")
            if created_by_id is not None:
                query_set = query_set.filter(created_by__id=created_by_id)
            if post_id is not None:
                query_set = query_set.filter(id=post_id)
            return query_set.order_by("-created_date")
        except (KeyError, TypeError) as exception:
            return Response(exception, status=400)

    def upsert_researchhub_posts(self, request):
        try:
            if request.data.get("post_id") is not None:
                return self.update_existing_researchhub_posts(request)
            else:
                return self.create_researchhub_post(request)
        except (KeyError, TypeError) as exception:
            return Response(exception, status=400)

    def create_researchhub_post(self, request):
        try:
            data = request.data
            created_by = request.user
            document_type = data.get("document_type")
            editor_type = data.get("editor_type")
            authors = data.get("authors", [])
            note_id = data.get("note_id", None)
            title = data.get("title", "")
            assign_doi = data.get("assign_doi", False)
            peer_review_is_requested = data.get("request_peer_review", False)
            doi = generate_doi() if assign_doi else None

            if assign_doi and created_by.get_balance() - CROSSREF_DOI_RSC_FEE < 0:
                return Response("Insufficient Funds", status=402)

            # logical ordering & not using signals to avoid race-conditions
            access_group = self.create_access_group(request)
            unified_document = self.create_unified_doc(request)
            if access_group is not None:
                unified_document.access_groups = access_group
                unified_document.save()

            rh_post = ResearchhubPost.objects.create(
                created_by=created_by,
                document_type=document_type,
                doi=doi,
                editor_type=CK_EDITOR if editor_type is None else editor_type,
                note_id=note_id,
                prev_version=None,
                preview_img=data.get("preview_img"),
                renderable_text=data.get("renderable_text"),
                title=title,
                bounty_type=data.get("bounty_type"),
                unified_document=unified_document,
            )
            file_name = f"RH-POST-{document_type}-USER-{created_by.id}.txt"
            full_src_file = ContentFile(data["full_src"].encode())
            rh_post.authors.set(authors)

            if not TESTING:
                if document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                    rh_post.discussion_src.save(file_name, full_src_file)
                else:
                    rh_post.eln_src.save(file_name, full_src_file)

            hub_ids = list(unified_document.hubs.values_list("id", flat=True))

            reset_unified_document_cache(
                hub_ids,
                document_type=[
                    ALL.lower(),
                    POSTS.lower(),
                    QUESTION.lower(),
                    BOUNTY.lower(),
                ],
                filters=[NEW, MOST_RSC],
                with_default_hub=True,
            )

            if assign_doi:
                crossref_response = register_doi(created_by, title, doi, rh_post)
                if crossref_response.status_code != 200:
                    return Response("Crossref API Failure", status=400)
                charge_doi_fee(created_by, rh_post)

            if peer_review_is_requested and note_id:
                request_peer_review(
                    request=request, requested_by=request.user, post=rh_post
                )

            return Response(ResearchhubPostSerializer(rh_post).data, status=200)

        except (KeyError, TypeError) as exception:
            log_error(exception)
            return Response(exception, status=400)

    def update_existing_researchhub_posts(self, request):
        data = request.data
        created_by = request.user
        authors = data.pop("authors", None)
        hubs = data.pop("hubs", None)
        title = data.get("title", "")
        assign_doi = data.get("assign_doi", False)
        doi = generate_doi() if assign_doi else None

        if assign_doi and created_by.get_balance() - CROSSREF_DOI_RSC_FEE < 0:
            return Response("Insufficient Funds", status=402)

        rh_post = ResearchhubPost.objects.get(id=data.get("post_id"))
        rh_post.doi = doi or rh_post.doi
        rh_post.save(update_fields=["doi"])

        serializer = ResearchhubPostSerializer(rh_post, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        post = serializer.instance

        file_name = (
            f'RH-POST-{request.data.get("document_type")}-USER-{request.user.id}.txt'
        )
        full_src_file = ContentFile(request.data["full_src"].encode())
        post.discussion_src.save(file_name, full_src_file)

        if type(authors) is list:
            rh_post.authors.set(authors)

        if type(hubs) is list:
            unified_doc = post.unified_document
            unified_doc.hubs.set(hubs)

        hub_ids = list(rh_post.unified_document.hubs.values_list("id", flat=True))

        reset_unified_document_cache(
            hub_ids,
            document_type=[ALL.lower(), POSTS.lower(), QUESTION.lower()],
            filters=[NEW, DISCUSSED, UPVOTED, HOT],
        )

        if assign_doi:
            crossref_response = register_doi(created_by, title, doi, rh_post)
            if crossref_response.status_code != 200:
                return Response("Crossref API Failure", status=400)
            charge_doi_fee(created_by, rh_post)

        return Response(serializer.data, status=200)

    def create_access_group(self, request):
        return None

    def create_unified_doc(self, request):
        try:
            request_data = request.data
            hubs = Hub.objects.filter(id__in=request_data.get("hubs")).all()
            uni_doc = ResearchhubUnifiedDocument.objects.create(
                document_type=request_data.get("document_type"),
            )
            uni_doc.hubs.add(*hubs)
            uni_doc.save()
            return uni_doc
        except (KeyError, TypeError) as exception:
            print("create_unified_doc: ", exception)


def request_peer_review(request, requested_by, post):
    doc_version = NoteContent.objects.filter(note_id=post.note_id).latest("id")
    serializer = PeerReviewRequestSerializer(
        data={
            "requested_by_user": requested_by.id,
            "unified_document": post.unified_document_id,
            "doc_version": doc_version.id,
        },
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return serializer.data


def generate_doi():
    return CROSSREF_DOI_PREFIX + "".join(
        random.choice(string.ascii_lowercase + string.digits)
        for _ in range(CROSSREF_DOI_SUFFIX_LENGTH)
    )


def register_doi(created_by, title, doi, rh_post):
    dt = datetime.today()
    context = {
        "timestamp": int(time.time()),
        "first_name": created_by.author_profile.first_name,
        "last_name": created_by.author_profile.last_name,
        "title": title,
        "publication_month": dt.month,
        "publication_day": dt.day,
        "publication_year": dt.year,
        "doi": doi,
        "url": f"{BASE_FRONTEND_URL}/post/{rh_post.id}/{rh_post.slug}",
    }
    crossref_xml = render_to_string("crossref.xml", context)
    files = {
        "operation": (None, "doMDUpload"),
        "login_id": (None, CROSSREF_LOGIN_ID),
        "login_passwd": (None, CROSSREF_LOGIN_PASSWORD),
        "fname": ("crossref.xml", crossref_xml),
    }
    crossref_response = requests.post(CROSSREF_API_URL, files=files)
    return crossref_response


def charge_doi_fee(created_by, rh_post):
    purchase = Purchase.objects.create(
        user=created_by,
        content_type=ContentType.objects.get(model="researchhubpost"),
        object_id=rh_post.id,
        purchase_method=Purchase.OFF_CHAIN,
        purchase_type=Purchase.DOI,
        amount=CROSSREF_DOI_RSC_FEE,
        paid_status=Purchase.PAID,
    )
    Balance.objects.create(
        user=created_by,
        content_type=ContentType.objects.get_for_model(purchase),
        object_id=purchase.id,
        amount=-CROSSREF_DOI_RSC_FEE,
    )
