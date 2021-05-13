from rest_framework import serializers

from analytics.models import PaperEvent, WebsiteVisits
from user.models import User


class WebsiteVisitsSerializer(serializers.ModelSerializer):

    class Meta:
        fields = '__all__'
        model = WebsiteVisits


class PaperEventSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=False,
        read_only=False,
        required=False
    )

    class Meta:
        model = PaperEvent
        exclude = []
