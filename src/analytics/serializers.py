from rest_framework import serializers

from .models import WebsiteVisits

class WebsiteVisitsSerializer(serializers.ModelSerializer):

    class Meta:
        fields = '__all__'
        model = WebsiteVisits
