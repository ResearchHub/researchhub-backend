from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.serializers.researchhub_unified_document_serializer import (
    DynamicUnifiedDocumentSerializer,
)
from researchhub_document.views.researchhub_unified_document_views import (
    ResearchhubUnifiedDocumentViewSet,
)
from user.related_models.user_model import User

from .models import UserSavedEntry, UserSavedList, UserSavedListPermission
from .serializers import (
    AddPermissionSerializer,
    ChangeDocumentSerializer,
    CreateListSerializer,
    RemovePermissionSerializer,
    UpdateListSerializer,
    UserSavedListDetailSerializer,
    UserSavedListPermissionSerializer,
    UserSavedListSerializer,
)

PERMISSION_DENIED = "Permission denied"
USER_NOT_FOUND = "User not found"


class UserSavedListViewSet(ModelViewSet):
    """
    ViewSet for managing user saved lists with enhanced functionality
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserSavedListSerializer

    def get_queryset(self):
        """Return lists that the user can view"""
        user = self.request.user

        # Get lists created by user
        own_lists = UserSavedList.objects.filter(created_by=user, is_removed=False)

        # Get lists shared with user
        shared_lists = UserSavedList.objects.filter(
            permissions__user=user, is_removed=False
        )

        # Get public lists
        public_lists = UserSavedList.objects.filter(is_public=True, is_removed=False)

        return (own_lists | shared_lists | public_lists).distinct()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return UserSavedListDetailSerializer
        return UserSavedListSerializer

    def _get_unified_document(self, u_doc_id=None, paper_id=None):
        """Helper method to get unified document by ID or paper ID"""
        if u_doc_id:
            return ResearchhubUnifiedDocument.objects.get(id=u_doc_id, is_removed=False)
        elif paper_id:
            return ResearchhubUnifiedDocument.objects.get(
                paper=paper_id, is_removed=False
            )
        else:
            raise ValueError("Either u_doc_id or paper_id must be provided")

    def _handle_integrity_error(self, error_msg="Operation failed"):
        """Helper method to handle IntegrityError consistently"""
        return Response({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        """Create a new list"""
        serializer = CreateListSerializer(data=request.data)
        if serializer.is_valid():
            try:
                list_obj = UserSavedList.objects.create(
                    created_by=request.user,
                    list_name=serializer.validated_data["list_name"],
                    description=serializer.validated_data.get("description", ""),
                    comment=serializer.validated_data.get("comment", ""),
                    is_public=serializer.validated_data.get("is_public", False),
                    tags=serializer.validated_data.get("tags", []),
                )

                response_serializer = UserSavedListSerializer(list_obj)
                return Response(
                    response_serializer.data, status=status.HTTP_201_CREATED
                )
            except IntegrityError:
                return self._handle_integrity_error("List name already exists")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """Update a list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_edit_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = UpdateListSerializer(data=request.data)
        if serializer.is_valid():
            try:
                if "list_name" in serializer.validated_data:
                    list_obj.list_name = serializer.validated_data["list_name"]
                if "description" in serializer.validated_data:
                    list_obj.description = serializer.validated_data["description"]
                if "is_public" in serializer.validated_data:
                    list_obj.is_public = serializer.validated_data["is_public"]
                if "tags" in serializer.validated_data:
                    list_obj.tags = serializer.validated_data["tags"]

                list_obj.save()

                response_serializer = UserSavedListSerializer(list_obj)
                return Response(response_serializer.data)
            except IntegrityError:
                return self._handle_integrity_error("List name already exists")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        """Delete a list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_admin_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            # Soft delete all entries
            UserSavedEntry.objects.filter(
                parent_list=list_obj, is_removed=False
            ).update(is_removed=True)

            # Soft delete the list
            list_obj.is_removed = True
            list_obj.save()

            return Response(
                {"success": True, "list_name": list_obj.list_name},
                status=status.HTTP_200_OK,
            )
        except (IntegrityError, ValueError) as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["post"])
    def add_document(self, request, pk=None):
        """Add a document to a list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_edit_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = ChangeDocumentSerializer(data=request.data)
        if serializer.is_valid():
            u_doc_id = serializer.validated_data.get("u_doc_id")
            paper_id = serializer.validated_data.get("paper_id")

            try:
                # Get the unified document
                unified_document = self._get_unified_document(u_doc_id, paper_id)

                # Check if document is already in the list (including soft-deleted)
                existing_entry = UserSavedEntry.objects.filter(
                    parent_list=list_obj,
                    unified_document=unified_document,
                ).first()

                if existing_entry:
                    if existing_entry.is_removed:
                        # Reactivate the soft-deleted entry
                        existing_entry.is_removed = False
                        existing_entry.save()
                        entry = existing_entry
                    else:
                        # Document is already active in the list
                        return Response(
                            {"error": "Document already in list"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                else:
                    # Create a new entry
                    try:
                        entry = UserSavedEntry.objects.create(
                            created_by=request.user,
                            parent_list=list_obj,
                            unified_document=unified_document,
                        )
                    except IntegrityError:
                        # Handle case where entry was created between check and create
                        existing_entry = UserSavedEntry.objects.get(
                            parent_list=list_obj,
                            unified_document=unified_document,
                        )
                        if existing_entry.is_removed:
                            # Reactivate the soft-deleted entry
                            existing_entry.is_removed = False
                            existing_entry.save()
                            entry = existing_entry
                        else:
                            # Document is already active in the list
                            return Response(
                                {"error": "Document already in list"},
                                status=status.HTTP_400_BAD_REQUEST,
                            )

                return Response(
                    {
                        "success": True,
                        "list_name": list_obj.list_name,
                        "document_id": unified_document.id,
                        "entry_id": entry.id,
                    },
                    status=status.HTTP_201_CREATED,
                )
            except ValueError:
                return Response(
                    {"error": "No document ID provided"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except ResearchhubUnifiedDocument.DoesNotExist:
                return Response(
                    {"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def remove_document(self, request, pk=None):
        """Remove a document from a list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_edit_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = ChangeDocumentSerializer(data=request.data)
        if serializer.is_valid():
            u_doc_id = serializer.validated_data.get("u_doc_id")
            paper_id = serializer.validated_data.get("paper_id")

            try:
                # Get the unified document
                unified_document = self._get_unified_document(u_doc_id, paper_id)

                # Remove the entry
                entry = UserSavedEntry.objects.filter(
                    parent_list=list_obj,
                    unified_document=unified_document,
                    is_removed=False,
                ).first()

                if entry:
                    entry.is_removed = True
                    entry.save()

                    return Response(
                        {
                            "success": True,
                            "list_name": list_obj.list_name,
                            "document_id": unified_document.id,
                        },
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {"error": "Document not found in list"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            except ValueError:
                return Response(
                    {"error": "No document ID provided"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except ResearchhubUnifiedDocument.DoesNotExist:
                return Response(
                    {"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def add_permission(self, request, pk=None):
        """Add permission for a user to access this list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_admin_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = AddPermissionSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data["username"]
            permission = serializer.validated_data["permission"]

            try:
                user = User.objects.get(username=username)

                # Don't allow adding permissions for the list owner
                if user == list_obj.created_by:
                    return Response(
                        {"error": "Cannot modify permissions for list owner"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Create or update permission
                perm_obj, created = UserSavedListPermission.objects.update_or_create(
                    list=list_obj,
                    user=user,
                    defaults={"permission": permission, "created_by": request.user},
                )

                response_serializer = UserSavedListPermissionSerializer(perm_obj)
                return Response(
                    response_serializer.data,
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
                )
            except User.DoesNotExist:
                return Response(
                    {"error": USER_NOT_FOUND}, status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def remove_permission(self, request, pk=None):
        """Remove permission for a user to access this list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_admin_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = RemovePermissionSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data["username"]

            try:
                user = User.objects.get(username=username)
                permission = UserSavedListPermission.objects.filter(
                    list=list_obj, user=user
                ).first()

                if permission:
                    permission.delete()
                    return Response(
                        {"success": True, "username": username},
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {"error": "Permission not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            except User.DoesNotExist:
                return Response(
                    {"error": USER_NOT_FOUND}, status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"])
    def permissions(self, request, pk=None):
        """Get all permissions for a list"""
        list_obj = self.get_object()

        # Check permissions
        if not self._can_view_list(request.user, list_obj):
            return Response(
                {"error": PERMISSION_DENIED}, status=status.HTTP_403_FORBIDDEN
            )

        permissions = list_obj.permissions.all()
        serializer = UserSavedListPermissionSerializer(permissions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _can_view_list(self, user, list_obj):
        """Check if user can view the list"""
        return (
            list_obj.created_by == user
            or list_obj.is_public
            or list_obj.permissions.filter(user=user).exists()
        )

    def _can_edit_list(self, user, list_obj):
        """Check if user can edit the list"""
        if list_obj.created_by == user:
            return True

        permission = list_obj.permissions.filter(user=user).first()
        return permission and permission.permission in ["EDIT", "ADMIN"]

    def _can_admin_list(self, user, list_obj):
        """Check if user can admin the list"""
        if list_obj.created_by == user:
            return True

        permission = list_obj.permissions.filter(user=user).first()
        return permission and permission.permission == "ADMIN"


class UserSavedSharedListView(APIView):
    """
    View for accessing shared lists via share token
    """

    permission_classes = []  # No authentication required for public shared lists

    def get(self, request, share_token):
        """Get a shared list by its share token"""
        try:
            list_obj = UserSavedList.objects.get(
                share_token=share_token, is_public=True, is_removed=False
            )

            # Get all entries including deleted documents
            entries = list_obj.usersavedentry_set.filter(is_removed=False)

            # Serialize the list with documents
            list_serializer = UserSavedListDetailSerializer(list_obj)
            data = list_serializer.data

            # Add document details
            documents_data = []
            for entry in entries:
                if entry.unified_document:
                    # Document still exists
                    doc_serializer = self._get_docs_serializer([entry.unified_document])
                    doc_data = doc_serializer.data[0] if doc_serializer.data else {}
                    doc_data["entry_id"] = entry.id
                    doc_data["is_deleted"] = False
                else:
                    # Document was deleted
                    doc_data = {
                        "entry_id": entry.id,
                        "is_deleted": True,
                        "title": entry.document_title_snapshot,
                        "document_type": entry.document_type_snapshot,
                        "deleted_date": entry.document_deleted_date,
                        "message": "This document has been deleted",
                    }
                documents_data.append(doc_data)

            data["documents"] = documents_data
            return Response(data, status=status.HTTP_200_OK)

        except UserSavedList.DoesNotExist:
            return Response(
                {"error": "List not found or not publicly shared"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def _get_docs_serializer(self, docs):
        context = ResearchhubUnifiedDocumentViewSet._get_serializer_context(self)
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
        return serializer
