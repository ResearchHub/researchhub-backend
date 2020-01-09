from user.models import Action

from discussion.lib import (
    check_thread_in_papers,
    check_comment_in_threads,
    check_reply_in_comments,
    check_reply_in_threads,
)
from discussion.models import (
    Comment, Reply, Thread, Vote as DiscussionVote
)


def get_latest_actions(cursor):
    actions = Action.objects.all().order_by('-id')[cursor:]
    next_cursor = cursor + len(actions)
    return actions, next_cursor


def get_authored_paper_updates(author, latest_actions):
    updates = []
    papers = author.authored_papers.all()
    for action in latest_actions:
        item = action.item

        if isinstance(item, DiscussionVote):
            if item.item.paper in papers:
                updates.append(action)
        else:
            if item.paper in papers:
                updates.append(action)
    return updates


def get_my_updates(user, actions):
    updates = []
    my_papers = user.author_profile.authored_papers.all()
    my_threads = Thread.objects.filter(created_by=user)
    my_comments = Comment.objects.filter(created_by=user)
    # my_replies = Reply.objects.filter(created_by=user)

    # TODO: Change this to a "subscribed to comment" model

    for action in actions:
        item = action.item

        if isinstance(item, Thread):
            # is it a thread on my paper?
            if check_thread_in_papers(item, my_papers):
                updates.append(action)

        elif isinstance(item, Comment):
            # is it a comment on my thread?
            if check_comment_in_threads(item, my_threads):
                updates.append(action)
            # is it a comment on my paper?
            # TODO
        elif isinstance(item, Reply):
            # is it a reply on my thread?
            if check_reply_in_threads(item, my_threads):
                updates.append(action)
            # is it a reply on my comment?
            if check_reply_in_comments(item, my_comments):
                updates.append(action)
            # is it a reply on my reply?


def filter_comments_on_my_threads(comments, threads):
    return [comment for comment in comments if comment.parent in threads]
