from rest_framework import serializers

from mailing_list.models import CommentSubscription, EmailRecipient


class CommentSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommentSubscription
        fields = "__all__"


class EmailRecipientSerializer(serializers.ModelSerializer):
    comment_subscription = CommentSubscriptionSerializer(read_only=True)
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
