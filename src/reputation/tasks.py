import math
import datetime
import pytz
import pandas as pd


from django.db.models import Q

from celery.decorators import periodic_task
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
from django.utils import timezone

from researchhub.settings import REWARD_SCHEDULE, APP_ENV
from researchhub.celery import app
from paper.models import Paper
from reputation.models import Contribution
from reputation.distributor import RewardDistributor
from utils.sentry import log_info

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
        create_author_contribution(
            Contribution.AUTHOR,
            user_id,
            paper_id,
            object_id
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
        if author.user:
            user = author.user
            data = {
                'contribution_type': contribution_type,
                'ordinal': i,
                'paper_id': paper_id,
                'content_type': content_type,
                'object_id': object_id
            }

            if user:
                data['user_id'] = user.id

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
    reward_dis.generate_distribution(item, amount=1)
    return items


@periodic_task(
    run_every=REWARD_SCHEDULE,
    priority=3,
    options={'queue': APP_ENV}
)
def distribute_rewards(
    starting_date=None,
    end_date=None,
    distribute=True,
    csv=False
):
    from paper.models import Vote as PaperVote
    from discussion.models import Vote as DisVote
    paper_vote = ContentType.objects.get_for_model(PaperVote)
    discussion_vote = ContentType.objects.get_for_model(DisVote)

    if end_date is None:
        end_date = datetime.datetime.now(tz=pytz.utc)

    # Checks if rewards should be distributed, given time config
    reward_dis = RewardDistributor()

    log_info('RD: Starting reward distribution')
    is_scheduled = reward_dis.is_scheduled()
    if not is_scheduled:
        log_info('RD: Reward distribution is not scheduled')
        return

    exclusions = [
        Q(contribution_type='CURATOR') |
        Q(
            user__email__in=(
                'pdj7@georgetown.edu',
                'lightning.lu7@gmail.com',
                'barmstrong@gmail.com',
            )
        )
    ]

    # Reward distribution logic
    last_distributed, last_distribution = reward_dis.get_last_distributions(
        distribute
    )
    if last_distributed.exists() and starting_date is not None:
        starting_date = last_distributed.last().distributed_date
    else:
        if last_distribution:
            starting_date = last_distribution.created_date
        else:
            starting_date = timezone.now().date() - timedelta(days=7)

    total_reward_amount = DEFAULT_REWARD
    if last_distribution:
        total_reward_amount = last_distribution.amount

    import pdb; pdb.set_trace()
    weekly_contributions = Contribution.objects.filter(
        created_date__gt=starting_date,
        created_date__lte=end_date,
        paper__is_removed=False,
        user__probable_spammer=False,
        user__is_suspended=False
    ).exclude(
        *exclusions
    )

    if not weekly_contributions.exists():
        log_info('RD: No weekly contributions exist')
        return

    contribution_count = weekly_contributions.count()
    paper_upvotes = weekly_contributions.filter(
        content_type=paper_vote,
        paper__uploaded_by__isnull=False
    )
    discussion_upvotes = weekly_contributions.filter(
        content_type=discussion_vote
    )
    total_upvotes = paper_upvotes.count() + discussion_upvotes.count()
    residual_count = contribution_count - total_upvotes

    main_reward_amount = math.floor(
        (total_reward_amount * 0.95) / total_upvotes
    )
    residual_reward_amount = math.ceil(
        (total_reward_amount * 0.05) / residual_count
    )

    vote_count = 0
    for i, contribution in enumerate(weekly_contributions.iterator()):
        print(f'{i}/{contribution_count}')
        if contribution.content_type in (paper_vote, discussion_vote):
            dis, residual = reward_dis.generate_distribution(
                contribution,
                amount=main_reward_amount,
                residual_amount=residual_reward_amount,
                distribute=distribute
            )
            vote_count += 1
        else:
            dis, residual = reward_dis.generate_distribution(
                contribution,
                amount=residual_reward_amount,
                distribute=distribute
            )

        if residual:
            print('carrying over residual')
            residual_reward_amount = math.ceil(
                (residual + total_reward_amount * 0.05) / (residual_count - ((i - vote_count)))
            )

    if distribute:
        last_distribution.distributed = True
        last_distribution.save()

    if csv:
        data = [item[1] for item in reward_dis.data.items()]
        df = pd.DataFrame(data)
        df.to_csv('pd_rsc_dist.csv')
