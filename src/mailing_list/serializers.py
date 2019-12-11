from rest_framework import serializers
from mailing_list.models import EmailRecipient


class EmailRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailRecipient
        fields = [
            'id',
            'email',
            'do_not_email',
            'is_opted_out',
            'is_subscribed',
            'bounced_date',
            'created_date',
            'updated_date',
        ]
