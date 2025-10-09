from rest_framework import serializers

from user_lists.models import List, ListItem


class ListItemSerializer(serializers.ModelSerializer):
    document_type = serializers.CharField(
        source="unified_document.document_type", read_only=True
    )

    class Meta:
        model = ListItem
        read_only_fields = ("id", "created_date", "document_type")
        extra_kwargs = {"parent_list": {"write_only": True}}
        fields = ("unified_document",) + read_only_fields + tuple(extra_kwargs.keys())

    def validate_unified_document(self, unified_document):
        supported_types = ["PAPER", "GRANT", "PREREGISTRATION"]

        if unified_document.document_type not in supported_types:
            raise serializers.ValidationError(
                f"Document type '{unified_document.document_type}' cannot be saved "
                f"to lists. Supported types: {', '.join(supported_types)}"
            )

        return unified_document

    def validate(self, attrs):
        parent_list = attrs.get("parent_list")

        if parent_list is None and self.instance is not None:
            parent_list = self.instance.parent_list

        if (
            parent_list is not None
            and parent_list.created_by_id != self.context["request"].user.id
        ):
            raise serializers.ValidationError(
                "You can only modify items on your own lists."
            )

        if (
            self.instance is not None
            and self.instance.created_by_id != self.context["request"].user.id
        ):
            raise serializers.ValidationError(
                "You can only modify your own list items."
            )

        return super().validate(attrs)


class ListSerializer(serializers.ModelSerializer):
    items = ListItemSerializer(many=True, read_only=True)

    class Meta:
        model = List
        read_only_fields = ("id", "created_date", "updated_date")
        fields = ("name", "items") + read_only_fields

    def validate(self, attrs):
        if (
            self.instance is not None
            and self.instance.created_by_id != self.context["request"].user.id
        ):
            raise serializers.ValidationError("You can only modify your own lists.")

        return super().validate(attrs)
