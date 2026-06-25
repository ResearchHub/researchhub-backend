from rest_framework import serializers

from institution.models import Institution


class InstitutionDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = [
            "id",
            "display_name",
        ]
        read_only_fields = fields
