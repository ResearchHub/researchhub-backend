from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType

from researchhub.celery import app
from paper.models import Paper
from reputation.models import Contribution
from reputation.distributor import RewardDistributor, Distributor


@app.task
def create_contribution(contribution_type, user_id, paper_id, object_id):
    if contribution_type == Contribution.SUBMITTER:
        content_type = ContentType.objects.get(
            app_label='paper',
            model='paper'
        )

        create_author_contribution(
            Contribution.AUTHOR,
            user_id,
            paper_id,
            object_id
        )
    else:
        content_type = ContentType.objects.get(
            app_label='user',
            model='user'
        )

    previous_contributions = Contribution.objects.filter(
        contribution_type=contribution_type,
        content_type=content_type,
        paper_id=paper_id
    ).order_by(
        'ordinal'
    )

    ordinal = 0
    if previous_contributions.exists():
        ordinal = previous_contributions.last().ordinal + 1

    Contribution.objects.create(
        contribution_type=contribution_type,
        user_id=user_id,
        ordinal=ordinal,
        paper_id=paper_id,
        content_type=content_type,
        object_id=object_id
    )


@app.task
def create_author_contribution(
    contribution_type,
    user_id,
    paper_id,
    object_id
):
    contributions = []
    content_type = ContentType.objects.get(model='author')
    authors = Paper.objects.get(id=paper_id).authors.all()
    for i, author in enumerate(authors.iterator()):
        user = author.user
        data = {
            'contribution_type': contribution_type,
            'ordinal': i,
            'paper_id': paper_id,
            'content_type': content_type,
            'object_id': object_id
        }

        if user:
            data['user'] = user.id

        contributions.append(
            Contribution(**data)
        )
    Contribution.objects.bulk_create(contributions)


@app.task
def distribute_round_robin(paper_id):
    reward_dis = RewardDistributor()
    paper = Paper.objects.get(id=paper_id)
    items = [
        paper.uploaded_by,
        *paper.authors.all(),
        *paper.votes.all(),
        *paper.threads.all()
    ]
    item = reward_dis.get_random_item(items)
    distribution = Distribution(

    )
    distributor = Distributor(

    )
    return items


# @periodic_task(
#     run_every=crontab(minute='0', hour='0', week='monday'),
#     priority=5
# )
# def distribute_weekly_rewards():
#     pass
