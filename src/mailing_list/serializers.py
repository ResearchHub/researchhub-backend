from rest_framework import serializers
from mailing_list.models import (
    DigestSubscription,
    EmailRecipient,
    PaperSubscription,
    ThreadSubscription,
    CommentSubscription,
    ReplySubscription
)
from utils.serializers import get_model_serializer


class EmailRecipientSerializer(serializers.ModelSerializer):
    digest_subscription = serializers.SerializerMethodField()
    paper_subscription = serializers.SerializerMethodField()
    thread_subscription = serializers.SerializerMethodField()
    comment_subscription = serializers.SerializerMethodField()
    reply_subscription = serializers.SerializerMethodField()
    user = serializers.CurrentUserDefault()

    class Meta:
        model = EmailRecipient
        fields = [
            'id',
            'email',
            'is_opted_out',
            'digest_subscription',
            'paper_subscription',
            'thread_subscription',
            'comment_subscription',
            'reply_subscription',
            'user',
        ]
        read_only_fields = [
            'id',
            'do_not_email',
            'bounced_date',
            'created_date',
            'updated_date',
            'next_cursor',
        ]

    def get_digest_subscription(self, obj):
        return self._get_subscription(DigestSubscription, obj)

    def get_paper_subscription(self, obj):
        return self._get_subscription(PaperSubscription, obj)

    def get_thread_subscription(self, obj):
        return self._get_subscription(ThreadSubscription, obj)

    def get_comment_subscription(self, obj):
        return self._get_subscription(CommentSubscription, obj)

    def get_reply_subscription(self, obj):
        return self._get_subscription(ReplySubscription, obj)

    def _get_subscription(self, model, obj):
        serializer = get_model_serializer(model)
        try:
            subscription = model.objects.get(email_recipient=obj)
            return serializer(subscription).data
        except model.DoesNotExist:
            return None
