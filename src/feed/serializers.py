from rest_framework import serializers

from hub.models import Hub
from paper.models import Paper
from user.models import Author, User

from .models import FeedEntry


class SimpleAuthorSerializer(serializers.ModelSerializer):
    """Minimal author serializer with just essential fields"""

    class Meta:
        model = Author
        fields = ["id", "first_name", "last_name", "profile_image"]


class SimpleUserSerializer(serializers.ModelSerializer):
    """Minimal user serializer with just essential fields"""

    profile_image = serializers.CharField(source="author_profile.profile_image")

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "profile_image"]


class ContentObjectSerializer(serializers.Serializer):
    """Base serializer for content objects (papers, posts, etc.)"""

    id = serializers.IntegerField()
    created_date = serializers.DateTimeField()
    hub = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()
    slug = serializers.CharField()

    def get_hub(self, obj):
        # FIXME: get primary hub
        hub = obj.hubs.first()
        if hub:
            return {"name": hub.name}
        return None

    def get_user(self, obj):
        # Handle different model attributes for user
        if hasattr(obj, "user"):
            user = obj.user
        elif hasattr(obj, "uploaded_by"):
            user = obj.uploaded_by
        else:
            return None

        return SimpleUserSerializer(user).data

    class Meta:
        fields = ["id", "created_date", "hub", "slug", "user"]
        abstract = True


class PaperSerializer(ContentObjectSerializer):
    journal = serializers.SerializerMethodField()
    authors = SimpleAuthorSerializer(many=True)
    title = serializers.CharField()
    abstract = serializers.CharField()
    doi = serializers.CharField()

    def get_journal(self, obj):
        journal_hub = obj.hubs.filter(
            namespace=Hub.Namespace.JOURNAL,
        ).first()
        if journal_hub:
            return {"name": journal_hub.name}
        return None

    class Meta(ContentObjectSerializer.Meta):
        model = Paper
        fields = ContentObjectSerializer.Meta.fields + [
            "abstract",
            "title",
            "doi",
            "journal",
            "authors",
        ]


class FeedEntrySerializer(serializers.ModelSerializer):
    """Serializer for feed entries that can reference different content types"""

    id = serializers.IntegerField()
    content_type = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    created_date = serializers.DateTimeField()
    action = serializers.CharField()
    user = serializers.SerializerMethodField()

    class Meta:
        model = FeedEntry
        fields = [
            "id",
            "content_type",
            "content_object",
            "created_date",
            "action",
            "user",
        ]

    def get_content_object(self, obj):
        """Return the appropriate serialized content object based on type"""
        if obj.content_type.model == "paper":
            return PaperSerializer(obj.item).data
        return None

    def get_content_type(self, obj):
        return obj.content_type.model.upper()

    def get_user(self, obj):
        return SimpleUserSerializer(obj.user).data
