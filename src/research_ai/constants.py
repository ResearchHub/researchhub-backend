from django.db import models

MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024


class ExpertiseLevel(models.TextChoices):
    """Target career stage for expert recommendations. Value is snake_case (API/DB), label is display."""

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
