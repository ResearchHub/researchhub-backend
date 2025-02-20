from rest_framework import serializers

from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import Author, User

from .models import FeedEntry


class SimpleUserSerializer(serializers.ModelSerializer):
    """Minimal user serializer with just essential fields"""

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "is_verified",
        ]


class SimpleAuthorSerializer(serializers.ModelSerializer):
    """Minimal author serializer with just essential fields"""

    user = SimpleUserSerializer()
    profile_image = serializers.CharField()

    class Meta:
        model = Author
        fields = [
            "id",
            "first_name",
            "last_name",
            "profile_image",
            "headline",
            "user",
        ]


class SimpleHubSerializer(serializers.ModelSerializer):
    """Minimal hub serializer with just essential fields"""

    class Meta:
        model = Hub
        fields = ["name", "slug"]


class ContentObjectSerializer(serializers.Serializer):
    """Base serializer for content objects (papers, posts, etc.)"""

    id = serializers.IntegerField()
    created_date = serializers.DateTimeField()
    hub = serializers.SerializerMethodField()
    slug = serializers.CharField()

    def get_hub(self, obj):
        # FIXME: get primary hub
        if hasattr(obj, "unified_document") and obj.unified_document:
            hub = next(iter(obj.unified_document.hubs.all()), None)
            if hub:
                return SimpleHubSerializer(hub).data
        return None

    class Meta:
        fields = ["id", "created_date", "hub", "slug", "user"]
        abstract = True


class PaperMetricsSerializer(serializers.Serializer):
    """Serializer for paper metrics including votes and comments."""

    votes = serializers.IntegerField(source="score", default=0)
    comments = serializers.IntegerField(source="discussion_count", default=0)
    reposts = serializers.IntegerField(default=0)  # TODO: Implement reposts
    saves = serializers.IntegerField(default=0)  # TODO: Implement saves


class PaperSerializer(ContentObjectSerializer):
    journal = serializers.SerializerMethodField()
    authors = SimpleAuthorSerializer(many=True)
    title = serializers.CharField()
    abstract = serializers.CharField()
    doi = serializers.CharField()
    metrics = PaperMetricsSerializer(source="*")

    def get_journal(self, obj):
        if not hasattr(obj, "unified_document") or not obj.unified_document:
            return None

        journal_hub = next(
            (
                hub
                for hub in obj.unified_document.hubs.all()
                if hub.namespace == Hub.Namespace.JOURNAL
            ),
            None,
        )

        if journal_hub:
            return {
                "id": journal_hub.id,
                "name": journal_hub.name,
                "slug": journal_hub.slug,
                "image": journal_hub.hub_image.url if journal_hub.hub_image else None,
                "description": journal_hub.description,
            }
        return None

    class Meta(ContentObjectSerializer.Meta):
        model = Paper
        fields = ContentObjectSerializer.Meta.fields + [
            "abstract",
            "title",
            "doi",
            "journal",
            "authors",
            "metrics",
        ]

class PostSerializer(ContentObjectSerializer):
    """Serializer for researchhub posts"""
    renderable_text = serializers.SerializerMethodField()
    title = serializers.CharField()

    def get_renderable_text(self, obj):
        text = obj.renderable_text[:255]
        if len(obj.renderable_text) > 255:
            text += "..."
        return text

    class Meta(ContentObjectSerializer.Meta):
        model = ResearchhubPost
        fields = ContentObjectSerializer.Meta.fields + ["title", "renderable_text"]


class BountySerializer(serializers.Serializer):
    amount = serializers.FloatField()
    bounty_type = serializers.CharField()
    document_type = serializers.SerializerMethodField()
    expiration_date = serializers.DateTimeField()
    hub = serializers.SerializerMethodField()
    id = serializers.IntegerField()
    paper = serializers.SerializerMethodField()
    status = serializers.CharField()

    def get_document_type(self, obj):
        return obj.unified_document.document_type

    def get_hub(self, obj):
        if obj.unified_document and obj.unified_document.hubs:
            # FIXME: get primary hub
            hub = obj.unified_document.hubs.first()
            return SimpleHubSerializer(hub).data
        return None

    def get_paper(self, obj):
        if (
            obj.unified_document
            and obj.unified_document.document_type == document_type.PAPER
        ):
            paper = obj.unified_document.paper
            return PaperSerializer(paper).data
        return None

    class Meta:
        fields = [
            "amount",
            "bounty_type",
            "document_type",
            "expiration_date",
            "hub",
            "id",
            "paper",
            "status",
        ]


class FeedEntrySerializer(serializers.ModelSerializer):
    """Serializer for feed entries that can reference different content types"""

    id = serializers.IntegerField()
    content_type = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    created_date = serializers.DateTimeField()
    action_date = serializers.DateTimeField()
    action = serializers.CharField()
    author = serializers.SerializerMethodField()

    class Meta:
        model = FeedEntry
        fields = [
            "id",
            "content_type",
            "content_object",
            "created_date",
            "action_date",
            "action",
            "author",
        ]

    def get_author(self, obj):
        """Return author data only if feed entry has an associated user"""
        if obj.user and hasattr(obj.user, "author_profile"):
            return SimpleAuthorSerializer(obj.user.author_profile).data
        return None

    def get_content_object(self, obj):
        """Return the appropriate serialized content object based on type"""
        match obj.content_type.model:
            case "bounty":
                # Use prefetched bounty if available
                if hasattr(obj, "_prefetched_bounty"):
                    return BountySerializer(obj._prefetched_bounty).data
                return BountySerializer(obj.item).data
            case "paper":
                # Use prefetched paper if available
                if hasattr(obj, "_prefetched_paper"):
                    return PaperSerializer(obj._prefetched_paper).data
                return PaperSerializer(obj.item).data
            case "researchhubpost":
                if hasattr(obj, "_prefetched_post"):
                    return PostSerializer(obj._prefetched_post).data
                return PostSerializer(obj.item).data
        return None

    def get_content_type(self, obj):
        return obj.content_type.model.upper()
