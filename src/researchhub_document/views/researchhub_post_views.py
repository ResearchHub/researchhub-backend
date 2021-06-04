from django.core.files.base import ContentFile
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import (
     AllowAny
)

from hub.models import Hub
from researchhub_document.related_models.constants.document_type \
    import DISCUSSION
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from researchhub_document.models import (
    ResearchhubPost, ResearchhubUnifiedDocument
)
from researchhub_document.serializers.researchhub_post_serializer \
    import ResearchhubPostSerializer
from user.models import User
from utils.http import GET, POST


@api_view(http_method_names=[GET, POST])
@permission_classes([AllowAny])  # change to IsAuthenticated
def handle_rh_posts_requests(request):
    if (request.method == "GET"):
        return get_researchhub_posts(request)
    else:
        return upsert_researchhub_posts(request)


def get_researchhub_posts(request):
    try:
        query_params = request.query_params
        query_set = ResearchhubPost.objects.all()
        created_by_id = query_params.get('created_by')
        if (created_by_id is not None):
            query_set = query_set.filter(created_by__id=created_by_id)
        return Response(
            ResearchhubPostSerializer(query_set, many=True,).data,
            status=200
        )
    except (KeyError, TypeError) as exception:
        return Response(exception, status=400)


def upsert_researchhub_posts(request):
    try:
        request_data = request.query_params
        prev_version_id = request_data.get('prev_version_id')
        if (prev_version_id is not None):
            return update_existing_researchhub_posts(request)
        else:
            return create_researchhub_post(request)
    except (KeyError, TypeError) as exception:
        return Response(exception, status=400)


def create_researchhub_post(request):
    try:
        request_data = request.query_params
        created_by_user = User.objects.get(
            id=request_data.get('created_by_id')
        )
        full_src_file = ContentFile(request_data['full_src'])
        is_discussion = request.data.get('document_type') == DISCUSSION
        editor_type = request_data.get('editor_type')

        # logical ordering & not using signals to avoid race-conditions
        access_group = create_access_group()
        unified_document = create_unified_doc()
        rh_post = ResearchhubPost.create(
            created_by=created_by_user,
            discussion_src=full_src_file if is_discussion else None,
            document_type=request_data.get('document_type'),
            editor_type=CK_EDITOR if editor_type is None else editor_type,
            eln_src=full_src_file if not is_discussion else None,
            prev_version=None,
            preview_img=request_data.get('preview_img'),
            renderable_text=request_data.get('renderable_text'),
            title=request_data.get('title')
        )
        if (access_group is not None):
            unified_document.access_group = access_group
            unified_document.save()
        rh_post.unified_document = unified_document
        rh_post.save()

        return Response(
            ResearchhubPostSerializer(
                ResearchhubPost.objects.get(id=rh_post.id)
            ).data,
            status=200
        )
    except (KeyError, TypeError) as exception:
        return Response(exception, status=400)


def update_existing_researchhub_posts(request):
    return Response("Update currently not supported", status=400)


def create_access_group(request):
    # TODO: calvinhlee - access group is for ELN
    return None


def create_unified_doc(request):
    request_data = request.query_params
    hubs = Hub.objects.filter(
        id__in=request_data.get('hub_ids')
    )
    return ResearchhubUnifiedDocument.create(
      document_type=request_data.get('document_type'),
      hubs=hubs,
    )
