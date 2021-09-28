from rest_framework.serializers import ModelSerializer, SerializerMethodField

from invite.models import OrganizationInvitation


class OrganizationInvitationSerializer(ModelSerializer):
    class Meta:
        model = OrganizationInvitation
        fields = '__all__'
