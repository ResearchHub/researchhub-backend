from rest_framework import serializers

from .models import UserSavedEntry, UserSavedList, UserSavedListPermission


class UserSavedListSerializer(serializers.ModelSerializer):
    share_url = serializers.SerializerMethodField()
    document_count = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    can_add_documents = serializers.SerializerMethodField()
    current_user_permission = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = UserSavedList
        fields = [
            "id",
            "list_name",
            "description",
            "is_public",
            "share_url",
            "tags",
            "document_count",
            "created_by_username",
            "created_date",
            "can_edit",
            "can_delete",
            "can_add_documents",
            "current_user_permission",
            "is_owner",
        ]

    def get_share_url(self, obj):
        return obj.get_share_url()

    def get_document_count(self, obj):
        return obj.usersavedentry_set.filter(is_removed=False).count()

    def get_created_by_username(self, obj):
        return obj.created_by.username if obj.created_by else None

    def get_can_edit(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return self._can_edit_list(request.user, obj)
        return False

    def get_can_delete(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return self._can_admin_list(request.user, obj)
        return False

    def get_can_add_documents(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return self._can_edit_list(request.user, obj)
        return False

    def get_current_user_permission(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            if obj.created_by == request.user:
                return "OWNER"
            permission = obj.permissions.filter(user=request.user).first()
            return permission.permission if permission else None
        return None

    def get_is_owner(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.created_by == request.user
        return False

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


class UserSavedListDetailSerializer(UserSavedListSerializer):
    documents = serializers.SerializerMethodField()

    class Meta(UserSavedListSerializer.Meta):
        fields = UserSavedListSerializer.Meta.fields + ["documents"]

    def get_documents(self, obj):
        entries = obj.usersavedentry_set.filter(is_removed=False)
        return UserSavedEntrySerializer(entries, many=True).data


class UserSavedEntrySerializer(serializers.ModelSerializer):
    document_info = serializers.SerializerMethodField()
    is_deleted = serializers.SerializerMethodField()

    class Meta:
        model = UserSavedEntry
        fields = [
            "id",
            "unified_document",
            "document_info",
            "is_deleted",
            "document_deleted",
            "document_deleted_date",
            "created_date",
        ]

    def get_document_info(self, obj):
        if obj.unified_document:
            return {
                "id": obj.unified_document.id,
                "title": self._get_document_title(obj.unified_document),
                "document_type": obj.unified_document.document_type,
                "url": obj.unified_document.get_url(),
                "score": obj.unified_document.score,
            }
        else:
            return {
                "id": None,
                "title": obj.document_title_snapshot,
                "document_type": obj.document_type_snapshot,
                "url": None,
                "score": None,
                "deleted": True,
            }

    def get_is_deleted(self, obj):
        return obj.document_deleted or obj.unified_document is None

    def _get_document_title(self, unified_doc):
        """Get document title safely"""
        try:
            if unified_doc.document_type == "PAPER":
                return (
                    unified_doc.paper.title if hasattr(unified_doc, "paper") else None
                )
            elif unified_doc.document_type == "DISCUSSION":
                post = unified_doc.posts.first()
                return post.title if post else None
            else:
                return getattr(unified_doc, "title", None)
        except (AttributeError, TypeError):
            return "Unknown Document"


class UserSavedListPermissionSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()

    class Meta:
        model = UserSavedListPermission
        fields = ["id", "user", "username", "email", "permission", "created_date"]

    def get_username(self, obj):
        return obj.user.username if obj.user else None

    def get_email(self, obj):
        return obj.user.email if obj.user else None


# Simplified serializers for specific operations
class CreateListSerializer(serializers.Serializer):
    list_name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    is_public = serializers.BooleanField(default=False)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, default=list
    )


class UpdateListSerializer(serializers.Serializer):
    list_name = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    is_public = serializers.BooleanField(required=False)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False
    )


class ChangeDocumentSerializer(serializers.Serializer):
    u_doc_id = serializers.IntegerField(required=False)
    paper_id = serializers.IntegerField(required=False)

    def validate(self, data):
        if not data.get("u_doc_id") and not data.get("paper_id"):
            raise serializers.ValidationError(
                "Either u_doc_id or paper_id must be provided"
            )
        return data


class AddPermissionSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    permission = serializers.ChoiceField(
        choices=["VIEW", "EDIT", "ADMIN"], default="VIEW"
    )


class RemovePermissionSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
