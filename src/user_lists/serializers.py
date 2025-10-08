from rest_framework import serializers

from user_lists.models import List, ListItem, ListItemDocumentContentType


class ListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListItem

        # TODO: is {unified_document_id + document_content_type} the way to load the right content on the FE?
        read_only_fields = ("id", "created_date")

        extra_kwargs = {
            "parent_list": {"write_only": True},
            "document_content_type": {"write_only": True},
        }

        fields = ("unified_document",) + read_only_fields + tuple(extra_kwargs.keys())

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

        document_content_type = attrs.get("document_content_type")

        if document_content_type:
            document_content_type = document_content_type.lower().strip()

            if document_content_type not in ListItemDocumentContentType.values:
                raise serializers.ValidationError(
                    f"Invalid document_content_type, expected one of:"
                    f"\n{', '.join(ListItemDocumentContentType.values)}"
                )

            attrs["document_content_type"] = document_content_type

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
