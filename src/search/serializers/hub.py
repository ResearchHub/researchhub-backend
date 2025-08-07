from search.base.serializers import ElasticsearchSerializer
from search.documents import HubDocument


class HubDocumentSerializer(ElasticsearchSerializer):
    class Meta:
        document = HubDocument
        fields = [
            "id",
            "name",
            "description",
            "slug",
            "paper_count",
            "discussion_count",
        ]

    def to_representation(self, instance):
        """
        Serialize hub document with specified fields.
        """
        data = super().to_representation(instance)

        # Filter to only include specified fields
        if hasattr(self.Meta, "fields"):
            filtered_data = {}
            for field in self.Meta.fields:
                if field in data:
                    filtered_data[field] = data[field]
            return filtered_data

        return data
