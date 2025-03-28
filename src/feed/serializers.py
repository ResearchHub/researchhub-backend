from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from hub.models import Hub
from paper.models import Paper
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.serializers.review_serializer import ReviewSerializer
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

    headline = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    user = SimpleUserSerializer()

    def get_headline(self, obj):
        if obj.headline and isinstance(obj.headline, dict) and "title" in obj.headline:
            return obj.headline.get("title")
        return None

    def get_profile_image(self, obj):
        if (
            hasattr(obj, "profile_image")
            and obj.profile_image.name
            and obj.profile_image.url
        ):
            return obj.profile_image.url

        return None

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
        if hasattr(obj, "unified_document") and obj.unified_document:
            hub = obj.unified_document.get_primary_hub()
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


class PostMetricsSerializer(serializers.Serializer):
    """Serializer for post metrics including votes and comments."""

    votes = serializers.IntegerField(source="score", default=0)
    comments = serializers.IntegerField(source="discussion_count", default=0)


class PaperSerializer(ContentObjectSerializer):
    journal = serializers.SerializerMethodField()
    authors = SimpleAuthorSerializer(many=True)
    raw_authors = serializers.ListField()
    title = serializers.CharField()
    abstract = serializers.CharField()
    doi = serializers.CharField()

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
        ]


class PostSerializer(ContentObjectSerializer):
    """Serializer for researchhub posts"""

    renderable_text = serializers.SerializerMethodField()
    title = serializers.CharField()
    type = serializers.CharField(source="document_type")
    fundraise = serializers.SerializerMethodField()

    def get_renderable_text(self, obj):
        text = obj.renderable_text[:255]
        if len(obj.renderable_text) > 255:
            text += "..."
        return text

    def get_fundraise(self, obj):
        """Return fundraise data if this is a preregistration post with fundraising"""
        if (
            hasattr(obj, "document_type")
            and obj.document_type == PREREGISTRATION
            and hasattr(obj, "unified_document")
            and obj.unified_document
            and hasattr(obj.unified_document, "fundraises")
            and obj.unified_document.fundraises.exists()
        ):
            fundraise = obj.unified_document.fundraises.first()
            context = getattr(self, "context", {})
            serializer = DynamicFundraiseSerializer(
                fundraise,
                context=context,
                _include_fields=[
                    "id",
                    "status",
                    "goal_amount",
                    "goal_currency",
                    "start_date",
                    "end_date",
                    "amount_raised",
                    "contributors",
                    "created_by",
                ],
            )
            return serializer.data
        return None

    class Meta(ContentObjectSerializer.Meta):
        model = ResearchhubPost
        fields = ContentObjectSerializer.Meta.fields + [
            "title",
            "renderable_text",
            "fundraise",
            "type",
        ]


class BountyContributionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.FloatField()
    author = SimpleAuthorSerializer(source="created_by.author_profile")


class BountySerializer(serializers.Serializer):
    amount = serializers.SerializerMethodField()
    bounty_type = serializers.CharField()
    comment = serializers.SerializerMethodField()
    contributors = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    expiration_date = serializers.DateTimeField()
    hub = serializers.SerializerMethodField()
    id = serializers.IntegerField()
    paper = serializers.SerializerMethodField()
    post = serializers.SerializerMethodField()
    status = serializers.CharField()
    contributions = serializers.SerializerMethodField()

    def get_amount(self, obj):
        """Return the amount from the bounty's comment"""
        if hasattr(obj, "item") and hasattr(obj.item, "bounties"):
            bounties = obj.item.bounties.all()
            return sum(bounty.amount for bounty in bounties)
        return 0

    def get_contributions(self, obj):
        """Return contributions from the bounty's comment"""
        if hasattr(obj, "item") and hasattr(obj.item, "bounties"):
            bounties = obj.item.bounties.all()
            if bounties:
                return [
                    BountyContributionSerializer(bounty).data for bounty in bounties
                ]
        return []

    def get_contributors(self, obj):
        """Return all contributors from child bounties"""
        contributors = set()

        # Get all child bounties
        if hasattr(obj, "children"):
            for child_bounty in obj.children.all():
                # Get contributor from child bounty
                user = child_bounty.created_by
                if user and hasattr(user, "author_profile") and user.author_profile:
                    contributors.add(user.author_profile)

        # Serialize contributors using SimpleAuthorSerializer
        if contributors:
            return SimpleAuthorSerializer(list(contributors), many=True).data
        return []

    def get_comment(self, obj):
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        if obj.item_content_type == comment_content_type:
            return CommentSerializer(obj.item).data
        return None

    def get_document_type(self, obj):
        return obj.unified_document.document_type

    def get_hub(self, obj):
        if obj.unified_document and obj.unified_document.hubs:
            hub = obj.unified_document.get_primary_hub()
            return SimpleHubSerializer(hub).data if hub else None
        return None

    def get_paper(self, obj):
        if (
            obj.unified_document
            and obj.unified_document.document_type == document_type.PAPER
        ):
            paper = obj.unified_document.paper
            return PaperSerializer(paper).data
        return None

    def get_post(self, obj):
        if obj.unified_document and hasattr(obj.unified_document, "posts"):
            post = obj.unified_document.posts.first()
            return PostSerializer(post).data
        return None

    class Meta:
        fields = [
            "amount",
            "bounty_type",
            "comment",
            "contributors",
            "document_type",
            "expiration_date",
            "hub",
            "id",
            "paper",
            "post",
            "status",
            "contributions",
        ]


class CommentMetricsSerializer(serializers.Serializer):
    """Serializer for comment metrics including votes."""

    votes = serializers.IntegerField(source="score", default=0)


class CommentSerializer(serializers.Serializer):
    comment_content_json = serializers.JSONField()
    comment_content_type = serializers.CharField()
    comment_type = serializers.CharField()
    document_type = serializers.SerializerMethodField()
    hub = serializers.SerializerMethodField()
    id = serializers.IntegerField()
    paper = serializers.SerializerMethodField()
    parent_id = serializers.IntegerField()
    post = serializers.SerializerMethodField()
    thread_id = serializers.IntegerField()
    review = serializers.SerializerMethodField()

    def get_document_type(self, obj):
        if obj.unified_document:
            return obj.unified_document.document_type
        return None

    def get_hub(self, obj):
        if obj.unified_document and obj.unified_document.hubs:
            # FIXMEL get primary hub
            hub = obj.unified_document.hubs.first()
            return SimpleHubSerializer(hub).data
        return None

    def get_paper(self, obj):
        """Return the paper associated with this comment if it exists"""
        if (
            obj.unified_document
            and obj.unified_document.document_type == document_type.PAPER
        ):
            paper = obj.unified_document.paper
            return PaperSerializer(paper).data
        return None

    def get_post(self, obj):
        """Return the post associated with this comment if it exists"""
        if obj.unified_document and hasattr(obj.unified_document, "posts"):
            post = obj.unified_document.posts.first()
            return PostSerializer(post).data
        return None

    def get_review(self, obj):
        """Return the review associated with this comment if it exists"""
        if hasattr(obj, "reviews") and obj.reviews.exists():
            review = obj.reviews.first()
            return ReviewSerializer(review).data
        return None

    class Meta:
        fields = [
            "comment_content_type",
            "comment_content_json",
            "comment_type",
            "document_type",
            "hub",
            "id",
            "paper",
            "parent_id",
            "post",
            "thread_id",
            "review",
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
            "metrics",
        ]

    def get_author(self, obj):
        """Return author data only if feed entry has an associated user"""
        if obj.user and hasattr(obj.user, "author_profile"):
            return SimpleAuthorSerializer(obj.user.author_profile).data
        return None

    def get_content_object(self, obj):
        if obj.content == {}:
            # Serialize if serialized content is not already present
            return serialize_feed_item(obj.item, obj.content_type)
        return obj.content

    def get_content_type(self, obj):
        return obj.content_type.model.upper()


def serialize_feed_metrics(item, item_content_type):
    """
    Serialize metrics for a feed item based on its content type.
    """
    metrics = {}
    if (
        item_content_type.model == "bounty"
        and item.item_content_type == ContentType.objects.get_for_model(RhCommentModel)
    ):
        # Metrics correspond to the comment associated with the bounty
        item = item.item

    if hasattr(item, "score"):
        metrics["votes"] = getattr(item, "score", 0)

    if hasattr(item, "get_discussion_count"):
        metrics["replies"] = item.get_discussion_count()

    if hasattr(item, "children_count"):
        metrics["replies"] = getattr(item, "children_count", 0)

    return metrics


def serialize_feed_item(feed_item, item_content_type):
    """
    Serialize an item to JSON based on its content type.

    Returns:
        The serialized JSON for the item or None if no serializer is found
    """

    match item_content_type.model:
        case "bounty":
            return BountySerializer(feed_item).data
        case "paper":
            return PaperSerializer(feed_item).data
        case "researchhubpost":
            return PostSerializer(feed_item).data
        case "rhcommentmodel":
            return CommentSerializer(feed_item).data
        case _:
            return None
