from rest_framework import serializers

from analytics.models import WebsiteVisits


class WebsiteVisitsSerializer(serializers.ModelSerializer):

    class Meta:
        fields = '__all__'
        model = WebsiteVisits
