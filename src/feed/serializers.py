from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from rest_framework import serializers

from hub.models import Hub
from paper.models import Paper
from purchase.serializers import DynamicPurchaseSerializer
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.serializers.review_serializer import ReviewSerializer
from user.models import Author, User

from .models import FeedEntry


class SimpleUserSerializer(serializers.ModelSerializer):
    """Minimal user serializer with just essential fields"""

    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "is_verified",
        ]

    def get_is_verified(self, obj):
        return obj.is_verified


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
        fields = ["id", "name", "slug"]


class SimpleReviewSerializer(serializers.ModelSerializer):
    """Minimal review serializer with just essential fields"""

    author = SimpleAuthorSerializer(source="created_by.author_profile")

    class Meta:
        model = ReviewSerializer.Meta.model
        fields = [
            "author",
            "id",
            "score",
        ]


class ContentObjectSerializer(serializers.Serializer):
    """Base serializer for content objects (papers, posts, etc.)"""

    id = serializers.IntegerField()
    created_date = serializers.DateTimeField()
    hub = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    subcategory = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    slug = serializers.CharField()
    unified_document_id = serializers.SerializerMethodField()

    def get_hub(self, obj):
        if hasattr(obj, "unified_document") and obj.unified_document:
            hub = obj.unified_document.get_primary_hub(fallback=True)
            if hub:
                return SimpleHubSerializer(hub).data
        return None

    def get_category(self, obj):
        """Return category hub if it exists"""
        if hasattr(obj, "unified_document") and obj.unified_document:
            category = obj.unified_document.hubs.filter(
                namespace=Hub.Namespace.CATEGORY
            ).first()
            if category:
                return SimpleHubSerializer(category).data
        return None

    def get_subcategory(self, obj):
        """Return subcategory hub if it exists"""
        if hasattr(obj, "unified_document") and obj.unified_document:
            subcategory = obj.unified_document.hubs.filter(
                namespace=Hub.Namespace.SUBCATEGORY
            ).first()
            if subcategory:
                return SimpleHubSerializer(subcategory).data
        return None

    def get_unified_document_id(self, obj):
        """Return unified document ID if it exists"""
        if hasattr(obj, "unified_document") and obj.unified_document:
            return obj.unified_document.id
        return None

    def get_bounty_data(self, obj):
        """Return bounty data from the unified document if it exists"""
        if hasattr(obj, "unified_document") and obj.unified_document:
            bounties = obj.unified_document.related_bounties.filter(parent__isnull=True)

            if not bounties.exists():
                return []

            return BountySerializer(bounties, many=True).data
        return []

    def get_purchase_data(self, obj):
        """Return purchase data from the unified document if it exists"""
        # Get purchases directly associated with the object
        if not hasattr(obj, "purchases"):
            return []

        context = getattr(self, "context", {})
        context["pch_dps_get_user"] = {
            "_include_fields": [
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            ]
        }
        serializer = DynamicPurchaseSerializer(
            obj.purchases.all(),
            many=True,
            context=context,
            _include_fields=["id", "amount", "user"],
        )
        return serializer.data

    def get_reviews(self, obj):
        """Return reviews from the unified document if it exists"""
        if hasattr(obj, "unified_document") and obj.unified_document:
            reviews = obj.unified_document.reviews.all()

            if not reviews.exists():
                return []

            return SimpleReviewSerializer(reviews, many=True).data
        return []

    class Meta:
        fields = [
            "id",
            "created_date",
            "hub",
            "category",
            "subcategory",
            "reviews",
            "slug",
            "user",
            "unified_document_id",
        ]
        abstract = True


class PaperSerializer(ContentObjectSerializer):
    journal = serializers.SerializerMethodField()
    authors = SimpleAuthorSerializer(many=True)
    raw_authors = serializers.ListField()
    title = serializers.CharField()
    abstract = serializers.CharField()
    doi = serializers.CharField()
    work_type = serializers.CharField()
    bounties = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()

    def get_bounties(self, obj):
        return self.get_bounty_data(obj)

    def get_purchases(self, obj):
        return self.get_purchase_data(obj)

    def get_journal(self, obj):
        if not hasattr(obj, "unified_document") or not obj.unified_document:
            return None

        journal_hubs = [
            hub
            for hub in obj.unified_document.hubs.all()
            if hub.namespace == Hub.Namespace.JOURNAL
        ]

        if not journal_hubs:
            return None

        researchhub_journal = None
        for hub in journal_hubs:
            if int(hub.id) == int(settings.RESEARCHHUB_JOURNAL_ID):
                researchhub_journal = hub
                break

        # Use ResearchHub Journal if found, otherwise use the first journal
        journal_hub = researchhub_journal or journal_hubs[0]

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
            "bounties",
            "purchases",
        ]


class PostSerializer(ContentObjectSerializer):
    """Serializer for researchhub posts"""

    renderable_text = serializers.SerializerMethodField()
    title = serializers.CharField()
    type = serializers.CharField(source="document_type")
    fundraise = serializers.SerializerMethodField()
    grant = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    bounties = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()

    def get_bounties(self, obj):
        return self.get_bounty_data(obj)

    def get_purchases(self, obj):
        return self.get_purchase_data(obj)

    def get_image_url(self, obj):
        if not obj.image:
            return None

        return default_storage.url(obj.image)

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
            # Prevent circular reference by limiting user serializer fields
            context["pch_dfs_get_created_by"] = {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "author_profile",
                ]
            }
            context["pch_dfs_get_contributors"] = {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "author_profile",
                ]
            }
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

    def get_grant(self, obj):
        """Return grant data if this is a grant post"""
        if (
            hasattr(obj, "document_type")
            and obj.document_type == GRANT
            and hasattr(obj, "unified_document")
            and obj.unified_document
            and hasattr(obj.unified_document, "grants")
            and obj.unified_document.grants.exists()
        ):
            grant = obj.unified_document.grants.first()
            context = getattr(self, "context", {})
            # Prevent circular reference by limiting user serializer fields
            context["pch_dgs_get_created_by"] = {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "author_profile",
                ]
            }
            context["pch_dgs_get_contacts"] = {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                    "author_profile",
                ]
            }
            serializer = DynamicGrantSerializer(
                grant,
                context=context,
                _include_fields=[
                    "id",
                    "status",
                    "amount",
                    "currency",
                    "organization",
                    "description",
                    "start_date",
                    "end_date",
                    "is_expired",
                    "is_active",
                    "created_by",
                    "contacts",
                    "applications",
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
            "grant",
            "type",
            "image_url",
            "bounties",
            "purchases",
        ]


class BountyContributionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.FloatField()
    author = SimpleAuthorSerializer(source="created_by.author_profile")


class BountySerializer(serializers.Serializer):
    amount = serializers.SerializerMethodField()
    bounty_type = serializers.CharField()
    contributors = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    expiration_date = serializers.DateTimeField()
    hub = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    subcategory = serializers.SerializerMethodField()
    id = serializers.IntegerField()
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

    def get_document_type(self, obj):
        return obj.unified_document.document_type

    def get_hub(self, obj):
        if obj.unified_document and obj.unified_document.hubs:
            hub = obj.unified_document.get_primary_hub(fallback=True)
            return SimpleHubSerializer(hub).data if hub else None
        return None

    def get_category(self, obj):
        """Return category hub if it exists"""
        if obj.unified_document:
            category = obj.unified_document.hubs.filter(
                namespace=Hub.Namespace.CATEGORY
            ).first()
            if category:
                return SimpleHubSerializer(category).data
        return None

    def get_subcategory(self, obj):
        """Return subcategory hub if it exists"""
        if obj.unified_document:
            subcategory = obj.unified_document.hubs.filter(
                namespace=Hub.Namespace.SUBCATEGORY
            ).first()
            if subcategory:
                return SimpleHubSerializer(subcategory).data
        return None

    class Meta:
        fields = [
            "amount",
            "bounty_type",
            "contributors",
            "document_type",
            "expiration_date",
            "hub",
            "category",
            "subcategory",
            "id",
            "status",
            "contributions",
        ]


class CommentSerializer(serializers.Serializer):
    author = serializers.SerializerMethodField()
    comment_content_json = serializers.JSONField()
    comment_content_type = serializers.CharField()
    comment_type = serializers.CharField()
    document_type = serializers.SerializerMethodField()
    hub = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    subcategory = serializers.SerializerMethodField()
    id = serializers.IntegerField()
    paper = serializers.SerializerMethodField()
    parent_comment = serializers.SerializerMethodField()
    parent_id = serializers.IntegerField()
    post = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()
    thread_id = serializers.IntegerField()
    bounties = serializers.SerializerMethodField()
    purchases = serializers.SerializerMethodField()

    def get_author(self, obj):
        return SimpleAuthorSerializer(obj.created_by.author_profile).data

    def get_bounties(self, obj):
        return BountySerializer(obj.bounties, many=True).data

    def get_document_type(self, obj):
        if obj.unified_document:
            return obj.unified_document.document_type
        return None

    def get_hub(self, obj):
        return SimpleHubSerializer(
            obj.unified_document.get_primary_hub(fallback=True)
        ).data

    def get_category(self, obj):
        """Return category hub if it exists"""
        if obj.unified_document:
            category = obj.unified_document.hubs.filter(
                namespace=Hub.Namespace.CATEGORY
            ).first()
            if category:
                return SimpleHubSerializer(category).data
        return None

    def get_subcategory(self, obj):
        """Return subcategory hub if it exists"""
        if obj.unified_document:
            subcategory = obj.unified_document.hubs.filter(
                namespace=Hub.Namespace.SUBCATEGORY
            ).first()
            if subcategory:
                return SimpleHubSerializer(subcategory).data
        return None

    def get_paper(self, obj):
        """Return the paper associated with this comment if it exists"""
        if (
            obj.unified_document
            and obj.unified_document.document_type == document_type.PAPER
        ):
            paper = obj.unified_document.paper
            paper_data = PaperSerializer(paper).data
            paper_data["unified_document_id"] = obj.unified_document.id
            return paper_data
        return None

    def get_parent_comment(self, obj):
        """Return the parent comment associated with this comment if it exists"""
        if obj.parent:
            return CommentSerializer(obj.parent).data
        return None

    def get_post(self, obj):
        """Return the post associated with this comment if it exists"""
        if obj.unified_document and hasattr(obj.unified_document, "posts"):
            post = obj.unified_document.posts.first()
            post_data = PostSerializer(post).data
            post_data["unified_document_id"] = obj.unified_document.id
            return post_data
        return None

    def get_review(self, obj):
        """Return the review associated with this comment if it exists"""
        if hasattr(obj, "reviews") and obj.reviews.exists():
            review = obj.reviews.first()
            return ReviewSerializer(review).data
        return None

    def get_purchases(self, obj):
        """Return purchases directly associated with this comment"""
        if hasattr(obj, "purchases") and obj.purchases.exists():
            context = getattr(self, "context", {})
            context["pch_dps_get_user"] = {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                    "is_verified",
                ]
            }
            serializer = DynamicPurchaseSerializer(
                obj.purchases.all(),
                many=True,
                context=context,
                _include_fields=["id", "amount", "user", "purchase_type"],
            )
            return serializer.data
        return []

    class Meta:
        fields = [
            "comment_content_type",
            "comment_content_json",
            "comment_type",
            "document_type",
            "hub",
            "category",
            "subcategory",
            "id",
            "paper",
            "parent_id",
            "post",
            "thread_id",
            "review",
            "purchases",
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
    hot_score_v2 = serializers.IntegerField()
    hot_score_breakdown = serializers.SerializerMethodField()
    external_metadata = serializers.SerializerMethodField()

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
            "hot_score_v2",
            "hot_score_breakdown",
            "external_metadata",
        ]

    def get_author(self, obj):
        """Return author data only if feed entry has an associated user"""
        if obj.user and hasattr(obj.user, "author_profile"):
            return SimpleAuthorSerializer(obj.user.author_profile).data
        return None

    def get_hot_score_breakdown(self, obj):
        """Return hot score breakdown if explicitly requested via query param."""
        request = self.context.get("request")
        if not request:
            return None

        # Only include if explicitly requested
        include = request.query_params.get("include_hot_score_breakdown", "false")
        if include.lower() != "true":
            return None

        # Return stored breakdown (already calculated)
        return obj.hot_score_v2_breakdown if obj.hot_score_v2_breakdown else None

    def get_external_metadata(self, obj):
        """
        Return external_metadata from Paper if content is a Paper.
        Returns None for non-paper content.
        """
        if obj.item and obj.content_type.model == "paper":
            if hasattr(obj.item, "external_metadata"):
                return obj.item.external_metadata
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
    if hasattr(item, "score"):
        metrics["votes"] = getattr(item, "score", 0)

    if hasattr(item, "get_discussion_count"):
        metrics["replies"] = item.get_discussion_count()

    if hasattr(item, "children_count"):
        metrics["replies"] = getattr(item, "children_count", 0)

    if item_content_type == ContentType.objects.get_for_model(
        Paper
    ) or item_content_type == ContentType.objects.get_for_model(ResearchhubPost):
        if hasattr(item, "unified_document"):
            metrics["review_metrics"] = item.unified_document.get_review_details()
        if hasattr(item, "citations"):
            metrics["citations"] = item.citations

        # Add altmetric data from external_metadata for Papers
        if item_content_type == ContentType.objects.get_for_model(Paper):
            if hasattr(item, "external_metadata") and item.external_metadata:
                altmetric_metrics = item.external_metadata.get("metrics", {})
                if altmetric_metrics:
                    metrics["altmetric_score"] = altmetric_metrics.get("score", 0.0)
                    metrics["facebook_count"] = altmetric_metrics.get(
                        "facebook_count", 0
                    )
                    metrics["twitter_count"] = altmetric_metrics.get("twitter_count", 0)
                    metrics["bluesky_count"] = altmetric_metrics.get("bluesky_count", 0)

    return metrics


def serialize_feed_item(feed_item, item_content_type):
    """
    Serialize an item to JSON based on its content type.

    Returns:
        The serialized JSON for the item or None if no serializer is found
    """

    match item_content_type.model:
        case "paper":
            return PaperSerializer(feed_item).data
        case "researchhubpost":
            return PostSerializer(feed_item).data
        case "rhcommentmodel":
            return CommentSerializer(feed_item).data
        case _:
            return None


class FundingFeedEntrySerializer(FeedEntrySerializer):
    """Serializer for funding feed entries"""

    is_nonprofit = serializers.SerializerMethodField()

    class Meta:
        model = FeedEntry
        fields = FeedEntrySerializer.Meta.fields + ["is_nonprofit"]

    def get_is_nonprofit(self, obj):
        if (
            obj.unified_document
            and hasattr(obj.unified_document, "fundraises")
            and obj.unified_document.fundraises.exists()
        ):
            return obj.unified_document.fundraises.first().nonprofit_links.exists()
        return None


class GrantFeedEntrySerializer(FeedEntrySerializer):
    """Serializer for grant feed entries"""

    class Meta:
        model = FeedEntry
        fields = FeedEntrySerializer.Meta.fields


class FeedFundraiseSerializer(serializers.Serializer):
    """Optimized fundraise serializer for fund-related feeds"""

    id = serializers.IntegerField()
    status = serializers.CharField()
    goal_currency = serializers.CharField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    created_date = serializers.DateTimeField()
    updated_date = serializers.DateTimeField()
    goal_amount = serializers.SerializerMethodField()
    amount_raised = serializers.SerializerMethodField()
    contributors = serializers.SerializerMethodField()

    def get_goal_amount(self, obj):
        from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
        
        usd_goal = float(obj.goal_amount)
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
        return {'usd': usd_goal, 'rsc': rsc_goal}

    def get_amount_raised(self, obj):
        from purchase.related_models.constants.currency import RSC, USD
        
        usd_raised = rsc_raised = 0
        if obj.escrow_id:
            usd_raised = obj.get_amount_raised(currency=USD)
            rsc_raised = obj.get_amount_raised(currency=RSC)
        
        return {'usd': usd_raised, 'rsc': rsc_raised}

    def get_contributors(self, obj):
        contributor_count = 0
        if obj.escrow_id:
            contributor_count = getattr(obj, 'contributor_count', 0)
        
        return {'total': contributor_count, 'top': []}


class FeedGrantSerializer(serializers.Serializer):
    """Optimized grant serializer for fund-related feeds"""

    id = serializers.IntegerField()
    status = serializers.CharField()
    currency = serializers.CharField()
    organization = serializers.CharField()
    description = serializers.CharField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    is_expired = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    applications = serializers.SerializerMethodField()

    def get_is_expired(self, obj):
        return bool(getattr(obj, 'is_expired_flag', 0))

    def get_is_active(self, obj):
        return bool(getattr(obj, 'is_active_flag', 0))

    def get_amount(self, obj):
        from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
        
        usd_amount = float(obj.amount)
        rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)
        
        return {
            'usd': usd_amount,
            'rsc': rsc_amount,
            'formatted': f'{usd_amount:,.2f} {obj.currency}',
        }

    def get_created_by(self, obj):
        if obj.created_by and hasattr(obj.created_by, 'author_profile'):
            return SimpleAuthorSerializer(obj.created_by.author_profile).data
        return None

    def get_applications(self, obj):
        applications = []
        for app in obj.applications.all():
            if app.applicant and hasattr(app.applicant, 'author_profile'):
                applications.append({
                    'id': app.id,
                    'created_date': app.created_date,
                    'applicant': SimpleAuthorSerializer(app.applicant.author_profile).data,
                    'preregistration_post_id': app.preregistration_post_id,
                })
        return applications


class FeedPostSerializer(serializers.Serializer):
    """Optimized post serializer for fund-related feeds"""

    id = serializers.IntegerField()
    created_date = serializers.DateTimeField()
    slug = serializers.CharField()
    title = serializers.CharField()
    renderable_text = serializers.SerializerMethodField()
    type = serializers.CharField(source='document_type')
    image_url = serializers.SerializerMethodField()
    unified_document_id = serializers.SerializerMethodField()
    hub = serializers.SerializerMethodField()
    fundraise = serializers.SerializerMethodField()
    grant = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()

    def get_renderable_text(self, obj):
        return obj.renderable_text  
        
    def get_image_url(self, obj):
        if obj.image:
            return default_storage.url(obj.image)
        return None

    def get_unified_document_id(self, obj):
        if obj.unified_document:
            return obj.unified_document.id
        return None

    def get_hub(self, obj):
        if obj.unified_document:
            hub = obj.unified_document.hubs.first()
            if hub:
                return SimpleHubSerializer(hub).data
        return None

    def get_fundraise(self, obj):
        from researchhub_document.related_models.constants.document_type import PREREGISTRATION
        
        if obj.unified_document and obj.document_type == PREREGISTRATION:
            fundraise = obj.unified_document.fundraises.first()
            if fundraise:
                return FeedFundraiseSerializer(fundraise).data
        return None

    def get_grant(self, obj):
        from researchhub_document.related_models.constants.document_type import GRANT
        
        if obj.unified_document and obj.document_type == GRANT:
            grant = obj.unified_document.grants.first()
            if grant:
                return FeedGrantSerializer(grant).data
        return None

    def get_reviews(self, obj):
        return []


class FeedFundingEntrySerializer(serializers.Serializer):
    """Optimized feed entry serializer for fund-related feeds"""

    id = serializers.IntegerField()
    content_type = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    action = serializers.CharField()
    action_date = serializers.DateTimeField()
    created_date = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()
    is_nonprofit = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    def get_content_type(self, obj):
        return obj.content_type.model.upper()

    def get_content_object(self, obj):
        return FeedPostSerializer(obj.item).data

    def get_created_date(self, obj):
        return obj.action_date

    def get_author(self, obj):
        if obj.item:
            created_by = getattr(obj.item, 'created_by', None)
            if created_by and hasattr(created_by, 'author_profile'):
                return SimpleAuthorSerializer(created_by.author_profile).data
        return None

    def get_metrics(self, obj):
        return {
            'votes': getattr(obj.item, 'score', 0),
            'comments': getattr(obj.item, 'discussion_count', 0),
        }

    def get_is_nonprofit(self, obj):
        if obj.unified_document and hasattr(obj.unified_document, 'fundraises'):
            fundraise = obj.unified_document.fundraises.first()
            if fundraise:
                return fundraise.nonprofit_links.exists()
        return False

    def get_user_vote(self, obj):
        request = self.context.get('request')
        if request and getattr(request.user, 'is_authenticated', False):
            vote = getattr(obj.item, '_user_vote', None)
            if vote:
                return {
                    'id': vote.id,
                    'vote_type': vote.vote_type,
                    'created_date': vote.created_date,
                }
        return None