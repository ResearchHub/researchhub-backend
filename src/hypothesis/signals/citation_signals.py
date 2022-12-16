from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.reaction_models import Vote
from hypothesis.models import Citation


@receiver(post_save, sender=Vote, dispatch_uid='update_citation_vote_score')
def update_citation_vote_score(
    sender,
    instance,
    **kwargs
):
    vote_item = instance.item
    if (isinstance(vote_item, Citation)):
        vote_item.vote_score = vote_item.get_vote_score()
        vote_item.save()