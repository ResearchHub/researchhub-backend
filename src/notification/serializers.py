from typing import Any

import rest_framework.serializers as serializers

from notification.models import Notification
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import DynamicUserSerializer, UserSerializer


def get_notification_context() -> dict[str, Any]:
    """Share the existing nested serializer fields between REST and live delivery."""
    return {
        "not_dns_get_action": {"_include_fields": ["content_type", "item"]},
        "not_dns_get_action_user": {
            "_include_fields": ["author_profile", "first_name", "last_name"]
        },
        "not_dns_get_recipient": {
            "_include_fields": ["author_profile", "first_name", "last_name"]
        },
        "not_dns_get_unified_document": {
            "_include_fields": ["documents", "document_type"]
        },
        "doc_duds_get_documents": {
            "_include_fields": ["id", "paper_title", "slug", "title"]
        },
        "usr_dus_get_author_profile": {"_include_fields": ["id", "profile_image"]},
        "pap_dpss_get_paper": {"_include_fields": ["id", "title"]},
        "pap_dps_get_unified_document": {
            "_include_fields": ["id", "title", "document_type", "slug"]
        },
    }


class NotificationSerializer(serializers.ModelSerializer):
    action_user = UserSerializer(read_only=True)
    unified_document = serializers.PrimaryKeyRelatedField(read_only=True)
    recipient = UserSerializer(
        read_only=False, default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = "__all__"
        model = Notification
        read_only_fields = [
            "id",
            "body",
            "extra",
            "action_user",
            "recipient",
            "created_date",
            "unified_document",
            "updated_date",
        ]


class DynamicNotificationSerializer(DynamicUnifiedDocumentSerializer):
    action_user = serializers.SerializerMethodField()
    recipient = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()

    class Meta:
        fields = "__all__"
        model = Notification

    def get_action_user(self, notification):
        context = self.context
        _context_fields = context.get("not_dns_get_action_user", {})
        serializer = DynamicUserSerializer(
            notification.action_user, context=context, **_context_fields
        )
        return serializer.data

    def get_recipient(self, notification):
        context = self.context
        _context_fields = context.get("not_dns_get_recipient", {})
        serializer = DynamicUserSerializer(
            notification.recipient, context=context, **_context_fields
        )
        return serializer.data

    def get_unified_document(self, notification):
        context = self.context
        _context_fields = context.get("not_dns_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            notification.unified_document, context=context, **_context_fields
        )
        return serializer.data
