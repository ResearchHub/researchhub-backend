from django.db import models

MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024


class ExpertiseLevel(models.TextChoices):
    """Target career stage for expert recommendations."""

    PHD_POSTDOCS = "PhD/PostDocs", "PhD/PostDocs"
    EARLY_CAREER = "Early Career Researchers", "Early Career Researchers"
    MID_CAREER = "Mid-Career Researchers", "Mid-Career Researchers"
    TOP_EXPERT = "Top Expert/World Renowned Expert", "Top Expert/World Renowned Expert"
    ALL_LEVELS = "All Levels", "All Levels"


class Region(models.TextChoices):
    """Geographic region filter for expert recommendations."""

    US = "US", "US"
    NON_US = "non-US", "non-US"
    EUROPE = "Europe", "Europe"
    ASIA_PACIFIC = "Asia-Pacific", "Asia-Pacific"
    AFRICA_MENA = "Africa & MENA", "Africa & MENA"
    ALL_REGIONS = "All Regions", "All Regions"


class Gender(models.TextChoices):
    """Gender preference for expert recommendations."""

    MALE = "Male", "Male"
    FEMALE = "Female", "Female"
    ALL_GENDERS = "All Genders", "All Genders"
