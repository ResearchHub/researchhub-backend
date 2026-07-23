from rest_framework import serializers

from mailing_list.models import (
    CommentSubscription,
    EmailRecipient,
)


def _get_model_serializer(model_arg):
    class GenericSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_arg
            fields = "__all__"

    return GenericSerializer


_SUBSCRIPTION_SERIALIZERS = {
    model: _get_model_serializer(model)
    for model in (CommentSubscription,)
}


class EmailRecipientSerializer(serializers.ModelSerializer):
    comment_subscription = serializers.SerializerMethodField()
    user = serializers.CurrentUserDefault()

    class Meta:
        model = EmailRecipient
        fields = [
            "id",
            "email",
            "is_opted_out",
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

    def get_comment_subscription(self, obj):
        return self._get_subscription(CommentSubscription, obj)

    def _get_subscription(self, model, obj):
        try:
            subscription = model.objects.get(email_recipient=obj)
            return _SUBSCRIPTION_SERIALIZERS[model](subscription).data
        except model.DoesNotExist:
            return None
