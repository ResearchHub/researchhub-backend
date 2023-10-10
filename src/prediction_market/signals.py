from django.dispatch import Signal, receiver

from prediction_market.models import PredictionMarketVote

# Custom signals
soft_deleted = Signal()
vote_saved = Signal()


@receiver(vote_saved, sender=PredictionMarketVote)
def handle_vote_saved(
    sender, instance, created, previous_vote_value, previous_bet_amount, **kwargs
):
    """
    Updates the votes_for/votes_against and bets_for/bets_against fields
    on the prediction market when a vote is saved.
    """
    pred_market = instance.prediction_market

    if created:
        pred_market.add_vote(instance)
    else:
        pred_market.update_vote(instance, previous_vote_value, previous_bet_amount)

    pred_market.save()


@receiver(soft_deleted, sender=PredictionMarketVote)
def handle_soft_delete(
    sender, instance, previous_vote_value, previous_bet_amount, **kwargs
):
    """
    Updates the votes_for/votes_against and bets_for/bets_against fields
    on the prediction market when a vote is soft deleted.
    """
    pred_market = instance.prediction_market
    pred_market.remove_vote(previous_vote_value, previous_bet_amount)
    pred_market.save()
