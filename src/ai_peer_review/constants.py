from django.db import models


class ReviewStatus(models.TextChoices):
    """Async AI job lifecycle for proposal review and RFP summary."""

    PENDING = "pending", "pending"
    PROCESSING = "processing", "processing"
    COMPLETED = "completed", "completed"
    FAILED = "failed", "failed"


class OverallRating(models.TextChoices):
    """Aggregate proposal quality from five dimension scores (5-15 scale)."""

    EXCELLENT = "excellent", "excellent"
    GOOD = "good", "good"
    POOR = "poor", "poor"


class ExpertDimensionScore(models.TextChoices):
    """Human editorial assessment per dimension (Table 4)."""

    HIGH = "high", "high"
    MEDIUM = "medium", "medium"
    LOW = "low", "low"
