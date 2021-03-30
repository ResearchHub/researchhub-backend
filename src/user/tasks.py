import logging

from django.apps import apps

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

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
from hub.models import Hub
from paper.tasks import censored_paper_cleanup
from paper.utils import reset_cache

from discussion.models import (Thread, Comment, Reply)


@app.task
def handle_spam_user_task(user_id):
    User = apps.get_model('user.User')
    user = User.objects.filter(id=user_id).first()
    if user:
        # user.papers.update(is_removed=True)
        user.paper_votes.update(is_removed=True)

        hub_ids = list(
            Hub.objects.filter(
                papers__in=list(user.papers.values_list(flat=True))
            ).values_list(
                flat=True
            ).distinct()
        )

        # Update discussions
        for thr in Thread.objects.filter(created_by=user):
            thr.remove_nested()
            thr.update_discussion_count()

        for com in Comment.objects.filter(created_by=user):
            com.remove_nested()
            com.update_discussion_count()

        for rep in Reply.objects.filter(created_by=user):
            rep.remove_nested()
            rep.update_discussion_count()
    reset_cache(hub_ids)


@app.task
def reinstate_user_task(user_id):
    User = apps.get_model('user.User')
    user = User.objects.get(id=user_id)

    papers = Paper.objects.filter(uploaded_by=user)
    papers.update(is_removed=False)
    user.paper_votes.update(is_removed=False)

    hub_ids = list(Hub.objects.filter(papers__in=list(user.papers.values_list(flat=True))).values_list(flat=True).distinct())

    # Update discussions
    for thr in Thread.objects.filter(created_by=user):
        thr.remove_nested()
        thr.update_discussion_count()

    for com in Comment.objects.filter(created_by=user):
        com.remove_nested()
        com.update_discussion_count()

    for rep in Reply.objects.filter(created_by=user):
        rep.remove_nested()
        rep.update_discussion_count()

    reset_cache(hub_ids, {}, None)


@app.task
def link_author_to_papers(author_id, orcid_account_id):
    Author = apps.get_model('user.Author')
    try:
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
    except (Author.DoesNotExist, SocialAccount.DoesNotExist) as e:
        logging.warning(
            f'{e} for author {author_id} orcid account {orcid_account_id}'
        )


@app.task
def link_paper_to_authors(paper_id):
    try:
        paper = Paper.objects.get(pk=paper_id)
        orcid_accounts = SocialAccount.objects.filter(
            provider=OrcidProvider.id
        )
        for orcid_account in orcid_accounts:
            works = get_orcid_works(orcid_account.extra_data)
            if check_doi_in_works(paper.doi, works):
                paper.authors.add(orcid_account.user.author_profile)
                paper.save()
                print(
                    f'Added author {orcid_account.user.author_profile.id}'
                    f' to paper {paper.id}'
                    f' on doi {paper.doi}'
                )
    except (Paper.DoesNotExist, SocialAccount.DoesNotExist) as e:
        logging.warning(f'{e} for paper {paper_id}')


def get_orcid_works(data):
    try:
        return data['activities-summary']['works']['group']
    except Exception as e:
        print(e)
    return []


def get_orcid_paper(work):
    doi = get_work_doi(work)
    if doi is not None:
        try:
            return Paper.objects.get(doi=doi)
        except Paper.DoesNotExist:
            return None
    return None


def check_doi_in_works(doi, works):
    for work in works:
        work_doi = get_work_doi(work)
        if doi == work_doi:
            return True
    return False


def get_work_doi(work):
    eids = work['external-ids']['external-id']
    for eid in eids:
        if eid['external-id-type'] == 'doi':
            return eid['external-id-value']
    return None


def get_latest_actions(cursor):
    Action = apps.get_model('user.Action')
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
