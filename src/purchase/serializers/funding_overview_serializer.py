from rest_framework import serializers


class CurrencyBreakdownSerializer(serializers.Serializer):
    rsc = serializers.FloatField()
    usd = serializers.FloatField()


class UnifiedDocumentMinimalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    slug = serializers.CharField()


class AuthorProfileMinimalSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    profile_image = serializers.CharField(allow_blank=True)


class ProposalCreatorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    author_profile = AuthorProfileMinimalSerializer()


class SupportedProposalSerializer(serializers.Serializer):
    unified_document = UnifiedDocumentMinimalSerializer()
    id = serializers.IntegerField()
    created_by = ProposalCreatorSerializer(allow_null=True)


class SupportedNonprofitSerializer(serializers.Serializer):
    """Subset of ``organizations.models.NonprofitOrg`` for funding overview."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    ein = serializers.CharField(allow_blank=True)
    endaoment_org_id = serializers.CharField(allow_blank=True)


class FundingOverviewSerializer(serializers.Serializer):
    """Serializer for funding overview response."""

    matched_funds = CurrencyBreakdownSerializer()
    distributed_funds = CurrencyBreakdownSerializer()
    supported_proposals = SupportedProposalSerializer(many=True)
    supported_nonprofits = SupportedNonprofitSerializer(many=True)
