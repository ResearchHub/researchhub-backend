import logging

from rest_framework import serializers

from discussion.models import Vote as DisVote
from discussion.serializers import VoteSerializer as DisVoteSerializer
from paper.models import Paper
from purchase.models import Purchase
from reputation.models import Distribution

logger = logging.getLogger(__name__)


class ProofRelatedField(serializers.RelatedField):
    """
    A custom field to use for the `source` generic relationship.
    """

    def to_representation(self, value):
        """
        Serialize tagged objects to a simple textual representation.
        """
        from paper.serializers import DynamicPaperSerializer
        from purchase.serializers import PurchaseSerializer

        if isinstance(value, DisVote):
            return DisVoteSerializer(value).data
        elif isinstance(value, Paper):
            paper_include_fields = ["id", "paper_title", "slug", "score"]
            return DynamicPaperSerializer(
                value, _include_fields=paper_include_fields
            ).data
        elif isinstance(value, Purchase):
            return PurchaseSerializer(value, context={"exclude_stats": True}).data

        logger.info(f"No representation for {value} / id: {value.id}")
        return None


class DistributionSerializer(serializers.ModelSerializer):
    proof_item = ProofRelatedField(read_only=True)

    class Meta:
        model = Distribution
        fields = "__all__"
        fields = "__all__"
