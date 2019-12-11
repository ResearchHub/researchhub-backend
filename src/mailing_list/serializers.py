from rest_framework import serializers
from mailing_list.models import EmailAddress


class EmailAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailAddress
        fields = '__all__'
