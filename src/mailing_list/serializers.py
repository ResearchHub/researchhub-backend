from rest_framework import serializers

from mailing_list.models import EmailRecipient


class EmailRecipientSerializer(serializers.ModelSerializer):
    user = serializers.CurrentUserDefault()

    class Meta:
        model = EmailRecipient
        fields = [
            "id",
            "email",
            "is_opted_out",
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
