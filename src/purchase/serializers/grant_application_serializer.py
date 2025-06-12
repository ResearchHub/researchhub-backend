from rest_framework import serializers

from purchase.models import GrantApplication
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicUserSerializer


class GrantApplicationSerializer(DynamicModelFieldSerializer):
    """Serializer for GrantApplication model with related data"""

    applicant = serializers.SerializerMethodField()
    preregistration_post_id = serializers.SerializerMethodField()
    grant_id = serializers.SerializerMethodField()

    class Meta:
        model = GrantApplication
        fields = [
            "id",
            "status",
            "created_date",
            "updated_date",
            "applicant",
            "preregistration_post_id",
            "grant_id",
        ]

    def get_applicant(self, application):
        """Get applicant author profile data"""
        context = self.context
        _context_fields = context.get("pch_dgs_get_applicant", {})
        serializer = DynamicUserSerializer(
            application.applicant, context=context, **_context_fields
        )
        return serializer.data

    def get_preregistration_post_id(self, application):
        """Get the preregistration post ID"""
        return (
            application.preregistration_post.id
            if application.preregistration_post
            else None
        )

    def get_grant_id(self, application):
        """Get the grant ID"""
        return application.grant.id if application.grant else None

