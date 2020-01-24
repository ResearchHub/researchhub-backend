from django.core.files.uploadedfile import SimpleUploadedFile
from paper.models import Flag, Paper, Vote

from user.tests.helpers import create_random_default_user
from utils.test_helpers import get_authenticated_post_response


class TestData:
    paper_title = ('Messrs Moony, Wormtail, Padfoot, and Prongs Purveyors of'
                   ' Aids to Magical Mischief-Makers are proud to present THE'
                   ' MARAUDER\'S MAP'
                   )
    paper_publish_date = '1990-10-01'


def create_flag(
    paper=None,
    created_by=None,
    reason='Create flag reason'
):
    if paper is None:
        paper = create_paper()
    if created_by is None:
        created_by = create_random_default_user('createflag')

    return Flag.objects.create(
        paper=paper,
        created_by=created_by,
        reason=reason
    )


def create_paper(
    title=TestData.paper_title,
    paper_publish_date=TestData.paper_publish_date,
    uploaded_by=None
):
    return Paper.objects.create(
        title=title,
        paper_publish_date=paper_publish_date,
        uploaded_by=uploaded_by
    )


def upvote_paper(paper, voter):
    """Returns vote on `paper` created by `voter` with type upvote."""
    return create_vote(created_by=voter, paper=paper, vote_type=Vote.UPVOTE)


def downvote_paper(paper, voter):
    """Returns vote on `paper` created by `voter` with type downvote."""
    return create_vote(created_by=voter, paper=paper, vote_type=Vote.DOWNVOTE)


def create_vote(created_by=None, paper=None, vote_type=Vote.UPVOTE):
    if created_by is None:
        created_by = create_random_default_user('paper')

    if paper is None:
        paper = create_paper()

    return Vote.objects.create(
        created_by=created_by,
        paper=paper,
        vote_type=vote_type
    )


def update_to_upvote(vote):
    vote.vote_type = Vote.UPVOTE
    vote.save(update_fields=['vote_type'])


def update_to_downvote(vote):
    vote.vote_type = Vote.DOWNVOTE
    vote.save(update_fields=['vote_type'])


def submit_paper_form(user, title='Building a Paper'):
    form_data = build_paper_form(title)
    return get_authenticated_post_response(
        user,
        '/api/paper/',
        form_data,
        content_type='multipart/form-data'
    )


def build_paper_form(title='Building a Paper'):
    file = SimpleUploadedFile('../config/paper.pdf', b'file_content')
    form = {
        'title': title,
        'file': file,
    }
    return form
