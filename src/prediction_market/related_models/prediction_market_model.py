from django.db import models

from prediction_market.related_models.prediction_market_vote_model import (
    PredictionMarketVote,
)
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

    votes_for = models.IntegerField(default=0)
    votes_against = models.IntegerField(default=0)

    bets_for = models.IntegerField(default=0)
    bets_against = models.IntegerField(default=0)

    def add_vote(self, vote):
        if vote.vote == PredictionMarketVote.VOTE_YES:
            self.votes_for = models.F("votes_for") + 1
            if vote.bet_amount is not None:
                self.bets_for = models.F("bets_for") + vote.bet_amount
        elif vote.vote == PredictionMarketVote.VOTE_NO:
            self.votes_against = models.F("votes_against") + 1
            if vote.bet_amount is not None:
                self.bets_against = models.F("bets_against") + vote.bet_amount

    def remove_vote(self, prev_vote_value=None, prev_bet_amount=None):
        if prev_vote_value == PredictionMarketVote.VOTE_YES:
            self.votes_for = models.F("votes_for") - 1
            if prev_bet_amount is not None:
                self.bets_for = models.F("bets_for") - prev_bet_amount
        elif prev_vote_value == PredictionMarketVote.VOTE_NO:
            self.votes_against = models.F("votes_against") - 1
            if prev_bet_amount is not None:
                self.bets_against = models.F("bets_against") - prev_bet_amount

    def update_vote(self, vote, prev_vote_value=None, prev_bet_amount=None):
        self.add_vote(vote)
        self.remove_vote(prev_vote_value, prev_bet_amount)
