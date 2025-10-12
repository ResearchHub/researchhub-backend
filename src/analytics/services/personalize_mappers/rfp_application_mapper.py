"""
Mapper for RFP (Grant) application events.

Handles mapping of GrantApplication records to Personalize interactions.
"""

from typing import Dict, List

from analytics.services.personalize_constants import EVENT_WEIGHTS, RFP_APPLIED
from analytics.services.personalize_mappers.base import BaseEventMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from purchase.related_models.grant_application_model import GrantApplication


class RfpApplicationMapper(BaseEventMapper):
    """Mapper for grant application (RFP application) events."""

    @property
    def event_type_name(self) -> str:
        return "rfp_application"

    def get_queryset(self, start_date=None, end_date=None):
        """
        Get grant applications queryset with optional date filters.

        Includes all grant applications.
        """
        queryset = GrantApplication.objects.select_related(
            "applicant", "grant", "grant__unified_document"
        ).all()

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset

    def map_to_interactions(self, application: GrantApplication) -> List[Dict]:
        """
        Map a GrantApplication to ONE RFP_APPLIED interaction.

        Args:
            application: GrantApplication instance

        Returns:
            List containing single interaction dictionary
        """
        interactions = []

        # Skip if no applicant
        if not application.applicant:
            return interactions

        # Skip if no grant
        if not application.grant:
            return interactions

        # Skip if grant has no unified document
        if not application.grant.unified_document:
            return interactions

        user_id = str(application.applicant.id)
        item_id = str(application.grant.unified_document.id)

        # Create RFP_APPLIED interaction
        interaction = {
            "USER_ID": user_id,
            "ITEM_ID": item_id,
            "EVENT_TYPE": RFP_APPLIED,
            "EVENT_VALUE": EVENT_WEIGHTS[RFP_APPLIED],
            "DEVICE": None,
            "TIMESTAMP": datetime_to_epoch_seconds(application.created_date),
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }
        interactions.append(interaction)

        return interactions
