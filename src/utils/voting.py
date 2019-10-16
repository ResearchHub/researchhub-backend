def calculate_score(obj, upvote_type, downvote_type):
    upvotes = obj.votes.filter(vote_type=upvote_type)
    downvotes = obj.votes.filter(vote_type=downvote_type)
    score = len(upvotes) - len(downvotes)
    return score
