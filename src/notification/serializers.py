import rest_framework.serializers as serializers

from notification.models import Notification
from researchhub_document.serializers import (
    DynamicUnifiedDocumentSerializer
)
from user.serializers import (
    UserActions,
    UserSerializer,
    DynamicActionSerializer,
    DynamicUserSerializer
)


class NotificationSerializer(serializers.ModelSerializer):
    action_user = UserSerializer(read_only=True)
    paper = serializers.PrimaryKeyRelatedField(read_only=True)
    unified_document = serializers.PrimaryKeyRelatedField(read_only=True)
    recipient = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )
    action = serializers.SerializerMethodField()
    paper_slug = serializers.SerializerMethodField()

    class Meta:
        fields = '__all__'
        model = Notification
        read_only_fields = [
            'id',
            'action',
            'action_user',
            'paper',
            'recipient',
            'created_date',
            'updated_date',
            'extra'
        ]

    def get_action(self, obj):
        return UserActions(data=[obj.action]).serialized

    def get_paper_slug(self, obj):
        paper = obj.paper
        if paper:
            return paper.slug
        return None


class DynamicNotificationSerializer(DynamicUnifiedDocumentSerializer):
    action = serializers.SerializerMethodField()
    action_user = serializers.SerializerMethodField()
    recipient = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()

    class Meta:
        fields = '__all__'
        model = Notification

    def get_action(self, notification):
        context = self.context
        _context_fields = context.get('not_dns_get_action', {})
        serializer = DynamicActionSerializer(
            notification.action,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_action_user(self, notification):
        context = self.context
        _context_fields = context.get('not_dns_get_action_user', {})
        serializer = DynamicUserSerializer(
            notification.action_user,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_recipient(self, notification):
        context = self.context
        _context_fields = context.get('not_dns_get_recipient', {})
        serializer = DynamicUserSerializer(
            notification.recipient,
            context=context,
            **_context_fields
        )
        return serializer.data

    def get_unified_document(self, notification):
        context = self.context
        _context_fields = context.get('not_dns_get_unified_document', {})
        serializer = DynamicUnifiedDocumentSerializer(
            notification.unified_document,
            context=context,
            **_context_fields
        )
        return serializer.data
