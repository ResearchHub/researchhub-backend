from rest_framework import serializers

from mailing_list.models import (
    BountyDigestSubscription,
    CommentSubscription,
    DigestSubscription,
    EmailRecipient,
    HubSubscription,
    PaperSubscription,
    ThreadSubscription,
)


def _get_model_serializer(model_arg):
    class GenericSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_arg
            fields = "__all__"

    return GenericSerializer


_SUBSCRIPTION_SERIALIZERS = {
    model: _get_model_serializer(model)
    for model in (
        BountyDigestSubscription,
        CommentSubscription,
        DigestSubscription,
        HubSubscription,
        PaperSubscription,
        ThreadSubscription,
    )
}


class EmailRecipientSerializer(serializers.ModelSerializer):
    digest_subscription = serializers.SerializerMethodField()
    bounty_digest_subscription = serializers.SerializerMethodField()
    paper_subscription = serializers.SerializerMethodField()
    hub_subscription = serializers.SerializerMethodField()
    thread_subscription = serializers.SerializerMethodField()
    comment_subscription = serializers.SerializerMethodField()
    user = serializers.CurrentUserDefault()

    class Meta:
        model = EmailRecipient
        fields = [
            "id",
            "email",
            "is_opted_out",
            "digest_subscription",
            "bounty_digest_subscription",
            "hub_subscription",
            "paper_subscription",
            "thread_subscription",
            "comment_subscription",
            "user",
        ]
        read_only_fields = [
            "id",
            "do_not_email",
            "bounced_date",
            "created_date",
            "updated_date",
            "next_cursor",
        ]

    def get_digest_subscription(self, obj):
        return self._get_subscription(DigestSubscription, obj)

    def get_bounty_digest_subscription(self, obj):
        return self._get_subscription(BountyDigestSubscription, obj)

    def get_paper_subscription(self, obj):
        return self._get_subscription(PaperSubscription, obj)

    def get_hub_subscription(self, obj):
        return self._get_subscription(HubSubscription, obj)

    def get_thread_subscription(self, obj):
        return self._get_subscription(ThreadSubscription, obj)

    def get_comment_subscription(self, obj):
        return self._get_subscription(CommentSubscription, obj)

    def _get_subscription(self, model, obj):
        try:
            subscription = model.objects.get(email_recipient=obj)
            return _SUBSCRIPTION_SERIALIZERS[model](subscription).data
        except model.DoesNotExist:
            return None
