import json

from discussion.models import Comment, Reply, Thread, Vote

from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


# REFACTOR: Replace default methods with kwargs

class TestData:
    thread_title = 'Thread Title'
    thread_text = 'This is a thread.'
    comment_text = 'This is a comment.'
    reply_text = 'This is a reply.'


def build_discussion_detail_url(self, discussion_type):
    url = self.base_url + f'paper/{self.paper.id}/'
    if discussion_type == 'paper':
        return url

    url += f'discussion/{self.thread.id}/'
    if discussion_type == 'thread':
        return url

    url += f'comment/{self.comment.id}/'
    if discussion_type == 'comment':
        return url

    url += f'reply/{self.reply.id}/'
    if discussion_type == 'reply':
        return url

    return None


def build_discussion_default_url(self, discussion_type):
    url = self.base_url + f'paper/'
    if discussion_type == 'paper':
        return url

    url += f'{self.paper.id}/discussion/'
    if discussion_type == 'thread':
        return url

    url += f'{self.thread.id}/comment/'
    if discussion_type == 'comment':
        return url

    url += f'{self.comment.id}/reply/'
    if discussion_type == 'reply':
        return url

    return None


def build_comment_data(parent, text):
    return {
        'parent': parent,
        'text': text,
    }


def build_reply_data(parent, text):
    return {
        'parent': parent,
        'text': text,
    }


def build_thread_form(paper, title, text):
    return {
        'paper': paper,
        'title': title,
        'text': json.dumps(text),
    }


def create_reply(
    parent=None,
    created_by=None,
    text=TestData.reply_text
):
    if parent is None:
        parent = create_comment()
    if created_by is None:
        created_by = create_random_default_user('reply')
    reply = Reply.objects.create(
        parent=parent,
        created_by=created_by,
        text=text
    )
    return reply


def create_comment(thread=None, created_by=None, text=TestData.comment_text):
    if thread is None:
        thread = create_thread()
    if created_by is None:
        created_by = create_random_default_user('comment')
    comment = Comment.objects.create(
        parent=thread,
        created_by=created_by,
        text=text
    )
    return comment


def create_thread(
    paper=None,
    created_by=None,
    title=TestData.thread_title,
    text=TestData.thread_text
):
    if paper is None:
        paper = create_paper()
    if created_by is None:
        created_by = create_random_default_user('thread')
    thread = Thread.objects.create(
        paper=paper,
        created_by=created_by,
        title=title,
        text=text
    )
    return thread


def upvote_discussion(item, voter):
    '''
    creates a new vote with vote_type upvote for the discussion item (one of
    comment, reply, thread)
    '''
    return create_vote(voter, item, Vote.UPVOTE)


def downvote_discussion(item, voter):
    '''
    creates a new vote with vote_type downvote for the discussion item (one of
    comment, reply, thread)
    '''
    return create_vote(voter, item, Vote.DOWNVOTE)


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
