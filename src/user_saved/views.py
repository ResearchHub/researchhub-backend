from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.serializers.researchhub_unified_document_serializer import (
    DynamicUnifiedDocumentSerializer,
)

from .models import UserSavedEntry, UserSavedList
from .serializers import (
    ChangeDocumentSerializer,
    CreateListSerializer,
    DeleteListSerializer,
    UserSavedListSerializer,
)


class UserSavedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        input_list_name = request.query_params.get("list_name")
        u_doc_id = request.query_params.get("u_doc_id")
        paper_id = request.query_params.get("paper_id")
        if input_list_name:
            try:
                user_list = UserSavedList.objects.get(
                    created_by=request.user, list_name=input_list_name, is_removed=False
                )
                docs = ResearchhubUnifiedDocument.objects.filter(
                    usersavedentry__parent_list=user_list,
                    usersavedentry__is_removed=False,
                )
                context = self._get_serializer_context()
                serializer = DynamicUnifiedDocumentSerializer(
                    docs,
                    _include_fields=[
                        "id",
                        "created_date",
                        "reviews",
                        "title",
                        "documents",
                        "paper_title",
                        "slug",
                        "is_removed",
                        "document_type",
                        "hubs",
                        "created_by",
                    ],
                    many=True,
                    context=context,
                )

                return Response(serializer.data, status=status.HTTP_200_OK)
            except UserSavedList.DoesNotExist:
                return Response(
                    {"error": "List not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
        if u_doc_id:
            # This path returns all user lists containing a specific document by uDocId
            if u_doc_id:
                lists = UserSavedList.objects.filter(
                    created_by=request.user,
                    is_removed=False,
                    usersavedentry__unified_document__id=u_doc_id,
                    usersavedentry__is_removed=False,
                )
                serializer = UserSavedListSerializer(lists, many=True)
                return Response([item["list_name"] for item in serializer.data])
        if paper_id:
            # This path returns all user lists containing a specific document by paperid
            lists = UserSavedList.objects.filter(
                created_by=request.user,
                is_removed=False,
                usersavedentry__unified_document__paper__id=paper_id,
                usersavedentry__is_removed=False,
            )
            serializer = UserSavedListSerializer(lists, many=True)
            return Response([item["list_name"] for item in serializer.data])
        else:
            lists = UserSavedList.objects.filter(
                created_by=request.user, is_removed=False
            )
            serializer = UserSavedListSerializer(lists, many=True)
            return Response([item["list_name"] for item in serializer.data])

    def post(self, request):
        """
        Create a new list for the authenticated user.
        Request body: {"list_name": "string"}
        """
        serializer = CreateListSerializer(data=request.data)
        if serializer.is_valid():
            list_name = serializer.validated_data["list_name"]
            try:
                UserSavedList.objects.create(
                    created_by=request.user, list_name=list_name
                )
                return Response(
                    {"success": True, "list_name": list_name},
                    status=status.HTTP_200_OK,
                )
            except IntegrityError as e:
                # Log the error for debugging
                print(f"IntegrityError during create: {e}")
                return Response(
                    {"error": "List name already exists"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        serializer = ChangeDocumentSerializer(data=request.data)
        if serializer.is_valid():
            list_name = serializer.validated_data["list_name"]
            u_doc_id = serializer.validated_data.get("u_doc_id", False)
            paper_id = serializer.validated_data.get("paper_id", False)
            delete_flag = serializer.validated_data["delete_flag"]
            try:
                user_list = UserSavedList.objects.get(
                    created_by=request.user, list_name=list_name, is_removed=False
                )

                # Support both UnifiedDocId and PaperID lookup, prefer former
                if u_doc_id:
                    unified_document = ResearchhubUnifiedDocument.objects.get(
                        id=u_doc_id,
                        is_removed=False,
                    )
                elif paper_id:
                    unified_document = ResearchhubUnifiedDocument.objects.get(
                        paper=paper_id,
                        is_removed=False,
                    )
                else:
                    return Response(
                        {"error": "No lookup key given"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if delete_flag:
                    UserSavedEntry.objects.filter(
                        created_by=request.user,
                        parent_list=user_list,
                        unified_document=unified_document,
                    ).delete()
                else:
                    UserSavedEntry.objects.create(
                        created_by=request.user,
                        parent_list=user_list,
                        unified_document=unified_document,
                    )

                return Response(
                    {
                        "success": True,
                        "list_name": list_name,
                        "document_id": unified_document.id,
                        "delete_flag": delete_flag,
                    },
                    status=status.HTTP_200_OK,
                )
            except UserSavedList.DoesNotExist:
                return Response(
                    {"error": "List not found"}, status=status.HTTP_404_NOT_FOUND
                )
            except ResearchhubUnifiedDocument.DoesNotExist:
                return Response(
                    {"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND
                )
            except IntegrityError:
                return Response(
                    {"error": "Document already in list"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        serializer = DeleteListSerializer(data=request.data)
        if serializer.is_valid():
            list_name = serializer.validated_data["list_name"]
            try:
                user_list = UserSavedList.objects.get(
                    created_by=request.user, list_name=list_name, is_removed=False
                )

                UserSavedEntry.objects.filter(
                    parent_list=user_list, is_removed=False
                ).update(is_removed=True)

                user_list.is_removed = True
                user_list.save()

                return Response(
                    {"success": True, "list_name": list_name}, status=status.HTTP_200_OK
                )
            except UserSavedList.DoesNotExist:
                return Response(
                    {"error": "List not found"}, status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _get_serializer_context(self):
        context = {
            "doc_duds_get_documents": {
                "_include_fields": [
                    "abstract",
                    "created_by",
                    "created_date",
                    "discussion_count",
                    "file",
                    "first_preview",
                    "hot_score",
                    "id",
                    "external_source",
                    "paper_publish_date",
                    "paper_title",
                    "pdf_url",
                    "image_url",
                    "is_open_access",
                    "oa_status",
                    "pdf_copyright_allows_display",
                    "authors",
                    "preview_img",
                    "renderable_text",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                    "citations",
                    "authorships",
                    "work_type",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "is_locked",
                    "slug",
                    "is_removed",
                    "hub_image",
                    "is_used_for_rep",
                ],
            },
            "pap_dps_get_authorships": {
                "_include_fields": [
                    "id",
                    "author",
                    "author_position",
                    "author_id",
                    "raw_author_name",
                    "is_corresponding",
                ]
            },
            "authorship::get_author": {"_include_fields": ["id", "profile_image"]},
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "pap_dps_get_authors": {
                "_include_fields": ["id", "first_name", "last_name"]
            },
            "doc_duds_get_fundraise": {
                "_include_fields": [
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                ]
            },
            "pch_dfs_get_contributors": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
        }
        return context
