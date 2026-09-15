from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Case, When

from user.models import Organization


def get_user_organizations(user):
    """Get all organizations which user has access to"""

    org_content_type = ContentType.objects.get_for_model(Organization)
    organization_ids = (
        user.permissions.annotate(
            org_id=Case(
                When(content_type=org_content_type, then="object_id"),
                When(
                    uni_doc_source__note__organization__isnull=False,
                    then="uni_doc_source__note__organization",
                ),
                output_field=models.PositiveIntegerField(),
            )
        )
        .filter(org_id__isnull=False)
        .values("org_id")
    )

    organizations = Organization.objects.filter(id__in=organization_ids)
    return organizations
