def calculate_score(obj, upvote_type, downvote_type):
    try:
        upvotes = obj.upvotes
    except AttributeError:
        upvotes = obj.votes.filter(vote_type=upvote_type)
    
    try:
        downvotes = obj.downvotes
    except AttributeError:
        downvotes = obj.votes.filter(vote_type=downvote_type)

    score = len(upvotes) - len(downvotes)
    return score
