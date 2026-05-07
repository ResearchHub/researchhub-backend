from django.conf import settings
from django.db import models

MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024

BASE_FRONTEND_URL = getattr(
    settings, "BASE_FRONTEND_URL", "https://www.researchhub.com"
)


class ExpertiseLevel(models.TextChoices):
    """Career stage for expert recommendations. Value: snake_case (API/DB), label: display."""

    PHD_POSTDOCS = "phd_postdocs", "PhD/PostDocs"
    EARLY_CAREER = "early_career", "Early Career Researchers"
    MID_CAREER = "mid_career", "Mid-Career Researchers"
    TOP_EXPERT = "top_expert", "Top Expert/World Renowned Expert"
    ALL_LEVELS = "all_levels", "All Levels"


class Region(models.TextChoices):
    """Geographic region filter. Value is snake_case (API/DB), label is display."""

    US = "us", "US"
    NON_US = "non_us", "non-US"
    EUROPE = "europe", "Europe"
    ASIA_PACIFIC = "asia_pacific", "Asia-Pacific"
    AFRICA_MENA = "africa_mena", "Africa & MENA"
    ALL_REGIONS = "all_regions", "All Regions"


class Gender(models.TextChoices):
    """Gender preference. Value is snake_case (API/DB), label is display."""

    MALE = "male", "Male"
    FEMALE = "female", "Female"
    ALL_GENDERS = "all_genders", "All Genders"


def get_choice_label(value: str, enum_class: type) -> str:
    """Return human-readable label for a choice value (e.g. for display in PDF/UI)."""
    for choice in enum_class:
        if choice.value == value:
            return choice.label
    return value


class EmailTemplateType(models.TextChoices):
    """Type of outreach email. Value stored in DB/API; label for display."""

    COLLABORATION = "collaboration", "collaboration"
    CONSULTATION = "consultation", "consultation"
    CONFERENCE = "conference", "conference"
    PEER_REVIEW = "peer-review", "peer-review"
    PUBLICATION = "publication", "publication"
    RFP_OUTREACH = "rfp-outreach", "rfp-outreach"
    CUSTOM = "custom", "custom"


VALID_EMAIL_TEMPLATE_KEYS = frozenset(e.value for e in EmailTemplateType)
DEFAULT_EMAIL_TEMPLATE_KEY = EmailTemplateType.COLLABORATION.value

EXPERT_REGISTERED_USER_LINK_WINDOW_DAYS = 7

EMAIL_TEMPLATE_PROMPT_FILES = {
    EmailTemplateType.CUSTOM.value: "email_custom.txt",
    EmailTemplateType.COLLABORATION.value: "email_collaboration.txt",
    EmailTemplateType.CONSULTATION.value: "email_consultation.txt",
    EmailTemplateType.CONFERENCE.value: "email_conference.txt",
    EmailTemplateType.PEER_REVIEW.value: "email_peer_review.txt",
    EmailTemplateType.PUBLICATION.value: "email_publication.txt",
    EmailTemplateType.RFP_OUTREACH.value: "email_rfp_outreach.txt",
}
