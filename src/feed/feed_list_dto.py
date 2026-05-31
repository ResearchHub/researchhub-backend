from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage
from rest_framework import serializers

from ai_peer_review.serializers import ProposalKeyInsightSerializer
from feed.hot_score_utils import calculate_adjusted_score
from feed.models import FeedEntry
from feed.serializers import SimpleAuthorSerializer, SimpleReviewSerializer
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.serializers.grant_serializer import DynamicGrantSerializer
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.serializers import DynamicUserSerializer


def serialize_fund_feed_metrics(item, item_content_type):
    """Metrics subset used by grant/funding feed cards."""
    metrics = {}
    if hasattr(item, "score"):
        metrics["votes"] = getattr(item, "score", 0)

    if hasattr(item, "get_discussion_count"):
        metrics["replies"] = item.get_discussion_count()

    if hasattr(item, "children_count"):
        metrics["replies"] = getattr(item, "children_count", 0)

    if hasattr(item, "unified_document") and item.unified_document is not None:
        metrics["review_metrics"] = item.unified_document.get_review_details()

    base_votes = metrics.get("votes", 0)
    metrics["adjusted_score"] = calculate_adjusted_score(base_votes, {})
    return metrics


def _serialize_review_author(review):
    user = review.created_by
    if not user:
        return None
    author = getattr(user, "author_profile", None)
    if not author:
        return None
    return SimpleAuthorSerializer(author).data


def _serialize_slim_application_fundraise(application):
    post = application.preregistration_post
    if not post or not hasattr(post, "unified_document") or not post.unified_document:
        return None

    ud = post.unified_document
    if not hasattr(ud, "fundraises"):
        return None

    fundraises = ud.fundraises.all()
    if not fundraises:
        return None
    fundraise = fundraises[0]

    usd_goal = float(fundraise.goal_amount)
    try:
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
    except AttributeError:
        rsc_goal = None

    nonprofit_data = None
    links = fundraise.nonprofit_links.all()
    if links:
        np = links[0].nonprofit
        nonprofit_data = {"id": np.id, "name": np.name}

    reviews = [
        {
            "id": r.id,
            "score": r.score,
            "is_assessed": r.is_assessed,
            "author": _serialize_review_author(r),
        }
        for r in ud.reviews.all()
    ]

    return {
        "id": fundraise.id,
        "title": post.title,
        "goal_amount": {"usd": usd_goal, "rsc": rsc_goal},
        "nonprofit": nonprofit_data,
        "reviews": reviews,
    }


def _serialize_application_key_insight(application, review_by_ud):
    proposal_review = None
    if application.preregistration_post_id:
        ud = application.preregistration_post.unified_document
        if ud is not None:
            proposal_review = review_by_ud.get(ud.id)
    if proposal_review is None:
        return None
    try:
        ki = proposal_review.key_insight
    except ObjectDoesNotExist:
        return None
    return ProposalKeyInsightSerializer(ki).data


def serialize_slim_grant_applications(grant, context):
    request = context.get("request")
    viewer = getattr(request, "user", None) if request else None
    is_grant_reviewer = (
        viewer is not None
        and getattr(viewer, "is_authenticated", False)
        and grant.created_by_id == viewer.id
    )
    include_key_insights = context.get("include_key_insights", False)

    review_by_ud = {}
    if include_key_insights:
        review_by_ud = {r.unified_document_id: r for r in grant.proposal_reviews.all()}

    application_data = []
    for application in grant.applications.all():
        author_profile = getattr(application.applicant, "author_profile", None)
        if not author_profile:
            continue

        ud = getattr(application.preregistration_post, "unified_document", None)
        if ud and ud.is_removed:
            continue

        if ud and not ud.is_public and not is_grant_reviewer:
            if not viewer or not getattr(viewer, "is_authenticated", False):
                continue
            if application.applicant_id != viewer.id:
                continue

        entry = {
            "applicant": SimpleAuthorSerializer(author_profile).data,
            "preregistration_post_id": (
                application.preregistration_post.id
                if application.preregistration_post
                else None
            ),
            "fundraise": _serialize_slim_application_fundraise(application),
        }
        if include_key_insights:
            entry["key_insight"] = _serialize_application_key_insight(
                application, review_by_ud
            )
        application_data.append(entry)

    return application_data


def _serialize_slim_grant(grant, context):
    created_by = None
    if grant.created_by and hasattr(grant.created_by, "author_profile"):
        profile = grant.created_by.author_profile
        if profile:
            created_by = SimpleAuthorSerializer(profile).data

    amount_serializer = DynamicGrantSerializer()
    return {
        "id": grant.id,
        "status": grant.status,
        "amount": amount_serializer.get_amount(grant),
        "currency": grant.currency,
        "organization": grant.organization,
        "short_title": grant.short_title,
        "description": grant.description,
        "start_date": grant.start_date,
        "end_date": grant.end_date,
        "is_expired": grant.is_expired(),
        "is_active": grant.is_active(),
        "created_by": created_by,
        "applications": serialize_slim_grant_applications(grant, context),
    }


class GrantFeedPostSerializer(serializers.Serializer):
    def to_representation(self, post):
        data = {
            "id": post.id,
            "slug": post.slug,
            "title": post.title,
            "type": post.document_type,
            "image_url": self._get_image_url(post),
            "unified_document_id": (
                post.unified_document_id if post.unified_document_id else None
            ),
            "grant": None,
        }

        if (
            post.document_type == GRANT
            and post.unified_document
            and hasattr(post.unified_document, "grants")
            and post.unified_document.grants.exists()
        ):
            grant = post.unified_document.grants.first()
            data["grant"] = _serialize_slim_grant(grant, self.context)

        return data

    @staticmethod
    def _get_image_url(post):
        if not post.image:
            return None
        return default_storage.url(post.image)


def _serialize_slim_fundraise(fundraise, context):
    usd_goal = float(fundraise.goal_amount)
    try:
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
    except AttributeError:
        rsc_goal = None

    created_by_fields = context.get("pch_dfs_get_created_by", {})
    created_by = DynamicUserSerializer(
        fundraise.created_by, context=context, **created_by_fields
    ).data

    contributor_fields = context.get("pch_dfs_get_contributors", {})
    aggregated = fundraise.get_contributors_summary()
    top = []
    for entry in aggregated.top:
        top.append(
            DynamicUserSerializer(
                entry.user, context=context, **contributor_fields
            ).data
        )

    return {
        "id": fundraise.id,
        "status": fundraise.status,
        "goal_amount": {"usd": usd_goal, "rsc": rsc_goal},
        "goal_currency": fundraise.goal_currency,
        "amount_raised": {
            "usd": fundraise.get_amount_raised(currency=USD),
            "rsc": fundraise.get_amount_raised(currency=RSC),
        },
        "start_date": fundraise.start_date,
        "end_date": fundraise.end_date,
        "contributors": {"total": aggregated.total, "top": top},
        "created_by": created_by,
    }


class FundingFeedPostSerializer(serializers.Serializer):
    """Minimal post payload for funding feed list responses."""

    def to_representation(self, post):
        data = {
            "id": post.id,
            "slug": post.slug,
            "title": post.title,
            "type": post.document_type,
            "image_url": self._get_image_url(post),
            "institution": getattr(post, "institution", None),
            "unified_document_id": (
                post.unified_document_id if post.unified_document_id else None
            ),
            "authors": [],
            "reviews": [],
            "fundraise": None,
        }

        if hasattr(post, "authors"):
            authors = post.authors.all()
            if authors:
                data["authors"] = SimpleAuthorSerializer(authors, many=True).data

        if post.unified_document and hasattr(post.unified_document, "reviews"):
            reviews = post.unified_document.reviews.all()
            if reviews:
                data["reviews"] = SimpleReviewSerializer(reviews, many=True).data

        if (
            post.document_type == PREREGISTRATION
            and post.unified_document
            and hasattr(post.unified_document, "fundraises")
            and post.unified_document.fundraises.exists()
        ):
            fundraise = post.unified_document.fundraises.first()
            data["fundraise"] = _serialize_slim_fundraise(fundraise, self.context)

        return data

    @staticmethod
    def _get_image_url(post):
        if not post.image:
            return None
        return default_storage.url(post.image)


class FundFeedListEntrySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField()
    content_type = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    action_date = serializers.DateTimeField()
    action = serializers.CharField()
    author = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()

    class Meta:
        model = FeedEntry
        fields = [
            "id",
            "content_type",
            "content_object",
            "action_date",
            "action",
            "author",
            "metrics",
        ]

    post_serializer_class = None

    def get_author(self, obj):
        if obj.user and hasattr(obj.user, "author_profile"):
            return SimpleAuthorSerializer(obj.user.author_profile).data
        return None

    def get_metrics(self, obj):
        return obj.metrics or {}

    def get_content_type(self, obj):
        return obj.content_type.model.upper()

    def get_content_object(self, obj):
        if not obj.item:
            return None
        serializer_class = self.post_serializer_class
        if serializer_class is None:
            return None
        return serializer_class(obj.item, context=self.context).data


class GrantFeedListEntrySerializer(FundFeedListEntrySerializer):
    post_serializer_class = GrantFeedPostSerializer


class FundingFeedListEntrySerializer(FundFeedListEntrySerializer):
    post_serializer_class = FundingFeedPostSerializer

    is_nonprofit = serializers.SerializerMethodField()
    nonprofit = serializers.SerializerMethodField()
    associated_grants = serializers.SerializerMethodField()

    class Meta(FundFeedListEntrySerializer.Meta):
        fields = FundFeedListEntrySerializer.Meta.fields + [
            "is_nonprofit",
            "nonprofit",
            "associated_grants",
        ]

    def get_nonprofit(self, obj):
        if not (obj.unified_document and hasattr(obj.unified_document, "fundraises")):
            return None
        fundraises = obj.unified_document.fundraises.all()
        if not fundraises:
            return None
        links = fundraises[0].nonprofit_links.all()
        if not links:
            return None
        np = links[0].nonprofit
        return {"id": np.id, "name": np.name}

    def get_is_nonprofit(self, obj):
        return self.get_nonprofit(obj) is not None

    def get_associated_grants(self, obj):
        if not obj.item or not hasattr(obj.item, "grant_applications"):
            return []

        results = []
        for app in obj.item.grant_applications.all():
            grant = app.grant
            num_applicants = getattr(grant, "num_applicants", None)
            if num_applicants is None:
                num_applicants = grant.applications.count()

            results.append(
                {
                    "id": grant.id,
                    "post_id": self._get_grant_post_id(grant),
                    "organization": grant.organization,
                    "short_title": grant.short_title,
                    "amount": str(grant.amount),
                    "currency": grant.currency,
                    "description": grant.description,
                    "status": grant.status,
                    "image": self._get_grant_image(grant),
                    "num_applicants": num_applicants,
                }
            )
        return results

    @staticmethod
    def _get_grant_post_id(grant):
        post = grant.unified_document.posts.first()
        return post.id if post else None

    @staticmethod
    def _get_grant_image(grant):
        post = grant.unified_document.posts.first()
        if post and post.image:
            return default_storage.url(post.image)
        return None
