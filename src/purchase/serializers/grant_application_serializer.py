from rest_framework import serializers

from purchase.models import GrantApplication
from purchase.related_models.grant_application_model import GrantApplicationStatus
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


class UpdateGrantApplicationStatusSerializer(serializers.ModelSerializer):
    """Serializer for updating GrantApplication status"""

    status = serializers.ChoiceField(
        choices=GrantApplicationStatus.choices,
        help_text="Status of the grant application",
    )

    class Meta:
        model = GrantApplication
        fields = ["status"]

    def validate_status(self, value):
        """Validate that the status is a valid choice"""
        if value not in [choice[0] for choice in GrantApplicationStatus.choices]:
            valid_choices = [choice[0] for choice in GrantApplicationStatus.choices]
            raise serializers.ValidationError(
                f"Invalid status. Must be one of: {valid_choices}"
            )
        return value
