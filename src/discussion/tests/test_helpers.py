from discussion.models import Comment, Reply, Thread

from user.test_helpers import create_random_default_user


class TestData:
    thread_title = 'Thread Title'
    thread_text = 'This is a thread.'
    comment_text = 'This is a comment.'
    reply_text = 'This is a reply.'


def create_default_reply():
    comment = create_default_comment()
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
        parent = create_default_comment()
    if user is None:
        user = create_random_default_user('reply')
    reply = Reply.objects.create(
        parent=parent,
        created_by=user,
        text=text
    )
    return reply


def create_default_comment():
    thread = create_default_thread()
    user = create_random_default_user('comment')
    text = TestData.comment_text
    comment = create_comment(thread, user, text)
    return comment


def create_comment(thread, user, text):
    comment = Comment.objects.create(
        parent=thread,
        created_by=user,
        text=text
    )
    return comment


def create_default_thread():
    paper = create_paper()
    user = TestHelper.create_random_default_user('thread')
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
