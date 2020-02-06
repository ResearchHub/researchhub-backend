from allauth.socialaccount.models import SocialAccount

from researchhub.celery import app
from discussion.lib import (
    check_thread_in_papers,
    check_comment_in_threads,
    check_reply_in_comments,
    check_reply_in_threads,
)
from discussion.models import (
    Comment, Reply, Thread, Vote as DiscussionVote
)
from paper.models import Paper
from user.models import Action, Author


@app.task
def link_author_to_papers(author_id, orcid_account_id):
    author = Author.objects.get(pk=author_id)
    orcid_account = SocialAccount.objects.get(pk=orcid_account_id)
    works = get_orcid_works(orcid_account.extra_data)
    for work in works:
        paper = get_orcid_paper(work)
        if paper is not None:
            paper.authors.add(author)
            paper.save()
            print(
                f'Added author {author.id}'
                f' to paper {paper.id}'
                f' on doi {paper.doi}'
            )


def get_orcid_works(data):
    return data['activities-summary']['works']['group']


def get_orcid_paper(work):
    eids = work['external-ids']['external-id']
    for eid in eids:
        if eid['external-id-type'] == 'doi':
            doi = eid['external-id-value']
            try:
                return Paper.objects.get(doi=doi)
            except Paper.DoesNotExist:
                pass
    return None


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

        if isinstance(item, Comment):
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

        elif isinstance(item, Thread):
            # is it a thread on my paper?
            if check_thread_in_papers(item, my_papers):
                updates.append(action)


def filter_comments_on_my_threads(comments, threads):
    return [comment for comment in comments if comment.parent in threads]
