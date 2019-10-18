from discussion.models import Comment, Reply, Thread, Vote

from paper.test_helpers import create_paper
from user.test_helpers import create_random_default_user


# REFACTOR: Replace default methods with kwargs

class TestData:
    thread_title = 'Thread Title'
    thread_text = 'This is a thread.'
    comment_text = 'This is a comment.'
    reply_text = 'This is a reply.'


def create_default_reply():
    comment = create_comment()
    user = create_random_default_user('reply')
    text = TestData.reply_text
    reply = create_reply(comment, user, text)
    return reply


def create_reply(
    parent=None,
    user=None,
    text=TestData.reply_text
):
    if parent is None:
        parent = create_comment()
    if user is None:
        user = create_random_default_user('reply')
    reply = Reply.objects.create(
        parent=parent,
        created_by=user,
        text=text
    )
    return reply


def create_comment(thread=None, created_by=None, text=TestData.comment_text):
    if thread is None:
        thread = create_default_thread()
    if created_by is None:
        created_by = create_random_default_user('comment')
    comment = Comment.objects.create(
        parent=thread,
        created_by=created_by,
        text=text
    )
    return comment


def create_default_thread():
    paper = create_paper()
    user = create_random_default_user('thread')
    title = TestData.thread_title
    text = TestData.thread_text
    thread = create_thread(paper, user, title, text)
    return thread


def create_thread(paper, user, title, text):
    thread = Thread.objects.create(
        paper=paper,
        created_by=user,
        title=title,
        text=text
    )
    return thread


def upvote_comment(created_by, comment):
    if created_by is None:
        created_by = create_random_default_user('upvoter')
    vote = Vote(item=comment, created_by=created_by, vote_type=Vote.UPVOTE)
    vote.save()
    return vote
