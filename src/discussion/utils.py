from django.db.models import Count, Q

from discussion.reaction_models import Vote

ORDERING_SCORE_ANNOTATION = Count("id", filter=Q(votes__vote_type=Vote.UPVOTE)) - Count(
    "id", filter=Q(votes__vote_type=Vote.DOWNVOTE)
)


def get_thread_id_from_path(request):
    DISCUSSION = 4
    thread_id = None
    path_parts = request.path.split("/")
    if path_parts[DISCUSSION] == "discussion":
        try:
            thread_id = int(path_parts[DISCUSSION + 1])
        except ValueError:
            print("Failed to get discussion id")
    return thread_id


def get_comment_id_from_path(request):
    COMMENT = 6
    comment_id = None
    path_parts = request.path.split("/")
    if path_parts[COMMENT] == "comment":
        try:
            comment_id = int(path_parts[COMMENT + 1])
        except ValueError:
            print("Failed to get comment id")
    return comment_id


def get_reply_id_from_path(request):
    REPLY = 8
    comment_id = None
    path_parts = request.path.split("/")
    if path_parts[REPLY] == "reply":
        try:
            comment_id = int(path_parts[REPLY + 1])
        except ValueError:
            print("Failed to get reply id")
    return comment_id
