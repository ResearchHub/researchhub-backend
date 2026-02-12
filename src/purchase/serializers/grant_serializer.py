from rest_framework import serializers

from purchase.models import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicAuthorSerializer, DynamicUserSerializer


class GrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grant
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
            "start_date",
        ]


class DynamicGrantSerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    contacts = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    applications = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()

    class Meta:
        model = Grant
        fields = "__all__"

    def get_created_by(self, grant):
        context = self.context
        _context_fields = context.get("pch_dgs_get_created_by", {})
        serializer = DynamicUserSerializer(
            grant.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_contacts(self, grant):
        context = self.context
        _context_fields = context.get("pch_dgs_get_contacts", {})
        serializer = DynamicUserSerializer(
            grant.contacts.all(), context=context, many=True, **_context_fields
        )
        return serializer.data

    def get_amount(self, grant):
        """
        Return amount in multiple currencies for display flexibility
        """
        usd_amount = float(grant.amount)

        # Handle case where no exchange rate exists (e.g., in tests)
        try:
            rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)
        except AttributeError:
            # Fallback to None if no exchange rate is available
            rsc_amount = None

        return {
            "usd": usd_amount,
            "rsc": rsc_amount,
            "formatted": f"{grant.amount:,.2f} {grant.currency}",
        }

    def get_is_expired(self, grant):
        """
        Check if the grant application deadline has passed
        """
        return grant.is_expired()

    def get_is_active(self, grant):
        """
        Check if the grant is currently accepting applications
        """
        return grant.is_active()

    def get_applications(self, grant):
        """Return grant applications with applicant information"""

        applications = grant.applications.select_related(
            "applicant__author_profile"
        ).all()

        application_data = []
        for application in applications:
            if (
                application.applicant
                and hasattr(application.applicant, "author_profile")
                and application.applicant.author_profile
            ):
                applicant_data = DynamicAuthorSerializer(
                    application.applicant.author_profile
                ).data
                application_data.append(
                    {
                        "id": application.id,
                        "created_date": application.created_date,
                        "applicant": applicant_data,
                        "preregistration_post_id": (
                            application.preregistration_post.id
                            if application.preregistration_post
                            else None
                        ),
                    }
                )

        return application_data

    def get_title(self, grant):
        """Return the title from the grant's associated post."""
        post = grant.unified_document.posts.first()
        if post:
            return post.title
        return None
