<<<<<<< HEAD
import math
import datetime

from celery.decorators import periodic_task
from celery.task.schedules import crontab
=======
>>>>>>> fd7a681644061a4941793ceed48d700c31d39af6
from django.contrib.contenttypes.models import ContentType

from researchhub.celery import app
from paper.models import Paper
<<<<<<< HEAD
from reputation.models import Contribution, DistributionAmount
from reputation.distributor import RewardDistributor

DEFAULT_REWARD = 1000000


@app.task
def create_contribution(
    contribution_type,
    instance_type,
    user_id,
    paper_id,
    object_id
):
    content_type = ContentType.objects.get(
        **instance_type
    )
    if contribution_type == Contribution.SUBMITTER:
=======
from reputation.models import Contribution


@app.task
def create_contribution(contribution_type, user_id, paper_id, object_id):
    if contribution_type == Contribution.PAPER:
        content_type = ContentType.objects.get(
            app_label='paper',
            model='paper'
        )

>>>>>>> fd7a681644061a4941793ceed48d700c31d39af6
        create_author_contribution(
            Contribution.AUTHOR,
            user_id,
            paper_id,
            object_id
        )
<<<<<<< HEAD
=======
    else:
        content_type = ContentType.objects.get(
            app_label='user',
            model='user'
        )
>>>>>>> fd7a681644061a4941793ceed48d700c31d39af6

    previous_contributions = Contribution.objects.filter(
        contribution_type=contribution_type,
        content_type=content_type,
<<<<<<< HEAD
        paper_id=paper_id
=======
>>>>>>> fd7a681644061a4941793ceed48d700c31d39af6
    ).order_by(
        'ordinal'
    )

    ordinal = 0
    if previous_contributions.exists():
<<<<<<< HEAD
        ordinal = previous_contributions.last().ordinal + 1

    Contribution.objects.create(
        contribution_type=contribution_type,
        user_id=user_id,
=======
        ordinal = previous_contributions.last().ordinal

    Contribution.objects.create(
        contribution_type=contribution_type,
        user=user_id,
>>>>>>> fd7a681644061a4941793ceed48d700c31d39af6
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
<<<<<<< HEAD


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
    reward_dis.generate_distribution(item, amount=1)
    return items


@periodic_task(
    run_every=crontab(minute='0', hour='0', day_of_week='sunday'),
    priority=5
)
def distribute_weekly_rewards():
    reward_dis = RewardDistributor()
    today = datetime.datetime.today()
    time_delta = datetime.timedelta(days=7)
    last_week = today - time_delta
    last_distribution_amount = DistributionAmount.objects.last()

    total_reward_amount = DEFAULT_REWARD
    if last_distribution_amount:
        total_reward_amount = last_distribution_amount.amount

    starting_date = datetime.datetime(
        year=today.year,
        month=today.month,
        day=last_week.day,
        hour=0,
        minute=0,
        second=0
    )

    weekly_contributions = Contribution.objects.filter(
        created_date__gte=starting_date,
        created_date__lt=today
    )
    if not weekly_contributions.exists():
        return

    paper_ids = weekly_contributions.values_list('paper')
    papers = Paper.objects.filter(id__in=[paper_ids])
    papers, prob_dist = reward_dis.get_papers_prob_dist(papers)

    reward_distribution = prob_dist * total_reward_amount

    for paper, reward in zip(papers, reward_distribution):
        contributions = weekly_contributions.filter(paper=paper)
        amount = math.floor(reward / contributions.count())
        for contribution in contributions:
            reward_dis.generate_distribution(contribution, amount=amount)
=======
>>>>>>> fd7a681644061a4941793ceed48d700c31d39af6
