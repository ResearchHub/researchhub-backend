from django.db import models

from utils.models import DefaultModel


class PredictionMarket(DefaultModel):
    REPLICATION_PREDICTION = "REPLICATION_PREDICTION"
    PREDICTION_TYPE_CHOICES = [
        (REPLICATION_PREDICTION, REPLICATION_PREDICTION),
    ]

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RESOLVED = "RESOLVED"
    STATUS_CHOICES = [
        (OPEN, OPEN),
        (CLOSED, CLOSED),
        (RESOLVED, RESOLVED),
    ]

    unified_document = models.ForeignKey(
        "researchhub_document.researchhubunifieddocument",
        related_name="prediction_markets",
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    prediction_type = models.CharField(
        choices=PREDICTION_TYPE_CHOICES,
        default=REPLICATION_PREDICTION,
        max_length=32,
        blank=False,
        null=False,
    )

    end_date = models.DateTimeField(blank=True, null=True)

    status = models.CharField(
        choices=STATUS_CHOICES,
        default=OPEN,
        max_length=32,
        blank=False,
        null=False,
    )

    def get_summary(self):
        total_votes = self.prediction_market_votes.count()
        votes_for = self.prediction_market_votes.filter(vote=True).count()
        votes_against = total_votes - votes_for
        return {
            "id": self.id,
            "votes": {
                "total": total_votes,
                "yes": votes_for,
                "no": votes_against,
            },
            "status": self.status,
            "prediction_type": self.prediction_type,
        }
