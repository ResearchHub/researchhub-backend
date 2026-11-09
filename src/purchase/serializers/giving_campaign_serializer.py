from rest_framework import serializers

from feed.serializers import SimpleHubSerializer
from purchase.models import Grant
from purchase.serializers.grant_serializer import DynamicGrantSerializer

FEATURED_GRANT_CONTEXT = {
    "pch_dgs_get_created_by": {
        "_include_fields": ("id", "author_profile", "first_name", "last_name")
    },
}

FEATURED_GRANT_FIELDS = (
    "id",
    "created_by",
    "amount",
    "currency",
    "organization",
    "short_title",
    "status",
    "start_date",
    "end_date",
    "funding_mechanism",
    "funding_pool",
    "post_id",
)


class GivingChallengeSerializer(serializers.Serializer):
    """A challenge's settings and its live progress."""

    id = serializers.IntegerField()
    kind = serializers.CharField()
    name = serializers.CharField()
    sponsor = serializers.CharField()
    hub = SimpleHubSerializer(allow_null=True)
    amount_usd = serializers.FloatField()
    donor_goal = serializers.IntegerField(allow_null=True)
    first_time_donors_only = serializers.BooleanField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    matched_usd = serializers.FloatField(allow_null=True)
    donor_count = serializers.IntegerField(allow_null=True)
    is_completed = serializers.BooleanField()


class GivingCampaignSerializer(serializers.Serializer):
    """A campaign's goal, live totals, featured RFP and challenges."""

    slug = serializers.SlugField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    goal_usd = serializers.FloatField()
    given_usd = serializers.FloatField()
    donor_count = serializers.IntegerField()
    featured_grant = serializers.SerializerMethodField()
    challenges = GivingChallengeSerializer(many=True)

    def get_featured_grant(self, summary: dict) -> dict | None:
        """Serialize the featured RFP with the fields its card shows."""
        grant: Grant | None = summary["featured_grant"]
        if grant is None:
            return None
        return DynamicGrantSerializer(
            grant, context=FEATURED_GRANT_CONTEXT, _include_fields=FEATURED_GRANT_FIELDS
        ).data
