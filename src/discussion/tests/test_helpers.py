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


def upvote_comment(comment, voter):
    return create_vote(voter, comment, Vote.UPVOTE)


def downvote_comment(comment, voter):
    return create_vote(voter, comment, Vote.DOWNVOTE)


def create_vote(created_by, item, vote_type):
    if created_by is None:
        created_by = create_random_default_user('voter')
    if item is None:
        item = create_paper()
    if vote_type is None:
        vote_type = Vote.UPVOTE
    vote = Vote(item=item, created_by=created_by, vote_type=vote_type)
    vote.save()
    return vote


def update_to_upvote(vote):
    vote.vote_type = Vote.UPVOTE
    vote.save(update_fields=['vote_type'])


def update_to_downvote(vote):
    vote.vote_type = Vote.DOWNVOTE
    vote.save(update_fields=['vote_type'])
