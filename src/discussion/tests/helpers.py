from discussion.reaction_models import Vote
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


def create_vote(created_by, item, vote_type):
    if created_by is None:
        created_by = create_random_default_user("voter")
    if item is None:
        item = create_paper()
    if vote_type is None:
        vote_type = Vote.UPVOTE
    vote = Vote(item=item, created_by=created_by, vote_type=vote_type)
    vote.save()
    return vote


def update_to_upvote(vote):
    vote.vote_type = Vote.UPVOTE
    vote.save(update_fields=["vote_type"])


def update_to_downvote(vote):
    vote.vote_type = Vote.DOWNVOTE
    vote.save(update_fields=["vote_type"])
