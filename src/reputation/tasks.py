import math
import datetime
import pytz
import numpy as np


from django.db.models import Q, Sum, Count

from celery.decorators import periodic_task
from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
from django.utils import timezone

from researchhub.settings import REWARD_SCHEDULE, REWARD_TIME, APP_ENV
from researchhub.celery import app
from paper.models import Paper
from reputation.models import Contribution, DistributionAmount
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
    reward_dis.generate_distribution(item, amount=1)
    return items


@periodic_task(
    run_every=REWARD_SCHEDULE,
    priority=3,
    options={'queue': APP_ENV}
)
def distribute_rewards():
    # Checks if rewards should be distributed, given time config
    today = datetime.datetime.now(tz=pytz.utc)
    static_date = datetime.datetime(
        year=2020,
        month=11,
        day=8,
        hour=23,
        minute=59,
    )

    reward_time_hour, reward_time_day, reward_time_week = list(
        map(int, REWARD_TIME.split(' '))
    )

    log_info('Distributing rewards')
    if reward_time_week:
        week = today.isocalendar()[1]
        if week % reward_time_week != 0:
            return
        # time_delta = datetime.timedelta(weeks=reward_time_week)
    elif reward_time_day:
        day = today.day
        if day % reward_time_day != 0:
            return
        # time_delta = datetime.timedelta(days=reward_time_day)
    elif reward_time_hour:
        hour = today.hour
        if hour % reward_time_hour != 0:
            return
        # time_delta = datetime.timedelta(hours=reward_time_hour)
    else:
        return

    # Reward distribution logic
    last_distribution = DistributionAmount.objects.filter(
        distributed=False
    )
    if not last_distribution.exists():
        last_distribution = DistributionAmount.objects.create()
    else:
        last_distribution = last_distribution.last()

    last_distributed = DistributionAmount.objects.filter(
        distributed=True
    )
    if last_distributed.exists():
        starting_date = last_distributed.last().distributed_date
    else:
        starting_date = last_distribution.created_date

    # last_week = today - time_delta
    # starting_date = datetime.datetime(
    #     year=last_week.year,
    #     month=last_week.month,
    #     day=last_week.day,
    #     hour=last_week.hour,
    #     minute=last_week.minute,
    #     second=last_week.second
    # )
    reward_dis = RewardDistributor()

    total_reward_amount = DEFAULT_REWARD
    if last_distribution:
        total_reward_amount = last_distribution.amount
    reward_amount = total_reward_amount * .95
    upvote_reward_amount = total_reward_amount - reward_amount

    weekly_contributions = Contribution.objects.filter(
        created_date__gt=starting_date,
        created_date__lte=static_date,
        paper__is_removed=False,
        user__probable_spammer=False,
        user__is_suspended=False
    ).exclude(
        Q(contribution_type='CURATOR') |
        Q(
            user__email__in=(
                'pdj7@georgetown.edu',
                'lightning.lu7@gmail.com',
                'barmstrong@gmail.com',
            )
        )
    )

    if not weekly_contributions.exists():
        return

    paper_ids = weekly_contributions.exclude(
        Q(contribution_type='UPVOTER')
    ).values_list(
        'paper'
    ).distinct()
    papers = Paper.objects.filter(id__in=[paper_ids])
    papers, prob_dist = reward_dis.get_papers_prob_dist(papers)

    reward_distribution = prob_dist * reward_amount
    contribution_types = (
        Contribution.AUTHOR,
        Contribution.SUBMITTER,
        Contribution.COMMENTER,
    )

    # Generating paper rewards (non upvotes)
    for paper, reward in zip(papers, reward_distribution):
        contribution_count = 0
        contributions = []
        for contribution_type in contribution_types:
            filtered_contributions = weekly_contributions.filter(
                paper=paper,
                contribution_type=contribution_type
            ).distinct('user')
            contribution_count += filtered_contributions.count()
            contributions.append(filtered_contributions)

        amount = math.floor(reward / contribution_count)
        for qs in contributions:
            for contribution in qs.iterator():
                reward_dis.generate_distribution(contribution, amount=amount)

    # Generating upvote rewards
    upvoters = weekly_contributions.filter(
        contribution_type=Contribution.UPVOTER
    )
    upvote_count = upvoters.count()
    upvote_amount = math.floor(upvote_reward_amount / upvote_count)
    if upvote_count > upvote_reward_amount:
        upvote_amount = 1
    for upvoter in upvoters.iterator():
        reward_dis.generate_distribution(upvoter, amount=upvote_amount)

    last_distribution.distributed = True
    last_distribution.save()


def reward_calculation(distribute):
    # Checks if rewards should be distributed, given time config
    today = datetime.datetime.now(tz=pytz.utc)
    static_date = datetime.datetime(
        year=2020,
        month=11,
        day=8,
        hour=23,
        minute=59,
    )

    reward_time_hour, reward_time_day, reward_time_week = list(
        map(int, REWARD_TIME.split(' '))
    )

    if reward_time_week:
        week = today.isocalendar()[1]
        if week % reward_time_week != 0:
            return
        # time_delta = datetime.timedelta(weeks=reward_time_week)
    elif reward_time_day:
        day = today.day
        if day % reward_time_day != 0:
            return
        # time_delta = datetime.timedelta(days=reward_time_day)
    elif reward_time_hour:
        hour = today.hour
        if hour % reward_time_hour != 0:
            return
        # time_delta = datetime.timedelta(hours=reward_time_hour)
    else:
        return

    # Reward distribution logic
    last_distribution = DistributionAmount.objects.filter(
        distributed=False
    )
    if not last_distribution.exists():
        if distribute:
            last_distribution = DistributionAmount.objects.create()
        else:
            last_distribution = None
    else:
        last_distribution = last_distribution.last()

    last_distributed = DistributionAmount.objects.filter(
        distributed=True
    )
    if last_distributed.exists():
        starting_date = last_distributed.last().distributed_date
    else:
        if last_distribution:
            starting_date = last_distribution.created_date
        else:
            starting_date = timezone.now().date() - timedelta(days=7)

    reward_dis = RewardDistributor()

    total_reward_amount = DEFAULT_REWARD
    if last_distribution:
        total_reward_amount = last_distribution.amount

    reward_amount = total_reward_amount * .95
    upvote_reward_amount = total_reward_amount - reward_amount

    weekly_contributions = Contribution.objects.filter(
        created_date__gt=starting_date,
        created_date__lte=static_date,
        paper__is_removed=False,
        user__probable_spammer=False,
        user__is_suspended=False
    ).exclude(
        Q(contribution_type='CURATOR') |
        Q(
            user__email__in=(
                'pdj7@georgetown.edu',
                # 'lightning.lu7@gmail.com',
                'barmstrong@gmail.com',
            )
        )
    )

    if not weekly_contributions.exists():
        return

    paper_ids = weekly_contributions.values_list(
        'paper'
    ).distinct()
    papers = Paper.objects.filter(id__in=[paper_ids])
    papers, prob_dist = reward_dis.get_papers_prob_dist(papers)

    reward_distribution = prob_dist * reward_amount
    contribution_types = (
        Contribution.AUTHOR,
        Contribution.SUBMITTER,
        Contribution.COMMENTER,
    )

    total_rewards = {}
    breakdown_rewards = {}
    count = 0
    total_count = papers.count()
    total_paper_scores = papers.aggregate(
        total_sum=Sum('score')
    )['total_sum']
    total_comment_scores = papers.aggregate(
        total_sum=Count('threads__votes', filter=Q(threads__votes__vote_type=1, threads__is_removed=False))
    )['total_sum']

    for paper, reward in zip(papers, reward_distribution):
        count += 1
        print('{} / {}'.format(count, total_count))
        contribution_count = 0
        contributions = []
        for contribution_type in contribution_types:
            filtered_contributions = weekly_contributions.filter(
                paper=paper,
                contribution_type=contribution_type
            ).distinct('user')
            contribution_count += filtered_contributions.count()
            contributions.append(filtered_contributions)

        for qs in contributions:
            for contribution in qs.iterator():

                breakdown_key = contribution.user.email
                if breakdown_rewards.get(breakdown_key):

                    if breakdown_rewards[breakdown_key].get(contribution.contribution_type + '_CONTRIBUTIONS'):
                        breakdown_rewards[breakdown_key][contribution.contribution_type + '_CONTRIBUTIONS'] += 1
                    else:
                        breakdown_rewards[breakdown_key][contribution.contribution_type + '_CONTRIBUTIONS'] = 1
                else:
                    breakdown_rewards[breakdown_key] = {}
                    breakdown_rewards[breakdown_key][contribution.contribution_type + '_CONTRIBUTIONS'] = 1

        if paper.uploaded_by:
            if breakdown_rewards.get(paper.uploaded_by.email):
                if breakdown_rewards[paper.uploaded_by.email].get('SUBMITTED_UPVOTE_COUNT'):
                    breakdown_rewards[paper.uploaded_by.email]['SUBMITTED_UPVOTE_COUNT'] += paper.score
                else:
                    breakdown_rewards[paper.uploaded_by.email]['SUBMITTED_UPVOTE_COUNT'] = paper.score

                if breakdown_rewards[paper.uploaded_by.email].get('PAPERS_UPLOADED'):
                    breakdown_rewards[paper.uploaded_by.email]['PAPERS_UPLOADED'].append((paper.id, paper.slug))
                else:
                    breakdown_rewards[paper.uploaded_by.email]['PAPERS_UPLOADED'] = [(paper.id, paper.slug)]
            else:
                breakdown_rewards[paper.uploaded_by.email] = {}
                breakdown_rewards[paper.uploaded_by.email]['SUBMITTED_UPVOTE_COUNT'] = paper.score
                breakdown_rewards[paper.uploaded_by.email]['PAPERS_UPLOADED'] = [(paper.id, paper.slug)]

    # Generating upvote rewards
    # TODO: CSV stuff here
    upvote_contrib = Contribution.UPVOTER
    upvoters = weekly_contributions.filter(
        contribution_type=Contribution.UPVOTER
    )
    upvote_count = upvoters.count()
    upvote_amount = math.floor(upvote_reward_amount / upvote_count)
    if upvote_count > upvote_reward_amount:
        upvote_amount = 1
    for contribution in upvoters.iterator():
        distributor = reward_dis.generate_distribution(contribution, amount=upvote_amount, distribute=False)
        if not distribute and distributor:
            total_key = distributor.recipient.email
            if total_rewards.get(total_key):
                total_rewards[total_key] += upvote_amount
            else:
                total_rewards[total_key] = upvote_amount

            breakdown_key = distributor.recipient.email
            if breakdown_rewards.get(breakdown_key):
                if breakdown_rewards[breakdown_key].get(upvote_contrib + '_CONTRIBUTIONS'):
                    breakdown_rewards[breakdown_key][upvote_contrib + '_CONTRIBUTIONS'] += 1
                else:
                    breakdown_rewards[breakdown_key][upvote_contrib + '_CONTRIBUTIONS'] = 1
                
                if contribution.content_type == 'discussion':
                    if breakdown_rewards[breakdown_key].get('UPVOTE_COMMENT_COUNT'):
                        breakdown_rewards[breakdown_key]['UPVOTE_COMMENT_COUNT'] += 1
                    else:
                        breakdown_rewards[breakdown_key]['UPVOTE_COMMENT_COUNT'] = 1
            else:
                breakdown_rewards[breakdown_key] = {}
                breakdown_rewards[breakdown_key][upvote_contrib] = upvote_amount
                breakdown_rewards[breakdown_key][upvote_contrib + '_CONTRIBUTIONS'] = 1
                if contribution.content_type == 'discussion':
                    breakdown_rewards[breakdown_key]['UPVOTE_COMMENT_COUNT'] = 1

    for key in breakdown_rewards:
        upload_upvote_count = breakdown_rewards[key]['SUBMITTED_UPVOTE_COUNT']
        comment_upvote_count = breakdown_rewards[key].get('UPVOTE_COMMENT_COUNT', 0)

        amount = ((upload_upvote_count + comment_upvote_count) / (total_paper_scores + total_comment_scores)) * reward_amount
        # distributor = reward_dis.generate_distribution(contribution, amount=0, distribute=False)

        if total_rewards.get(key):
            total_rewards[key] += amount
        else:
            total_rewards[key] = amount

    headers = 'Total Upvotes: {}, Total Paper Upvotes: {}, Total Comment Upvotes: {}\n'.format(total_paper_scores + total_comment_scores, total_paper_scores, total_comment_scores,)
    headers += 'email,Bonus RSC Amount,Paper Submissions,Upvotes,Upvotes on Submissions,Comments,Upvotes on Comments,Papers Uploaded\n'

    total_sorted = {k: v for k, v in sorted(total_rewards.items(), key=lambda item: item[1], reverse=True)}
    for key in total_sorted:

        base_paper_string = 'https://www.researchhub.com/paper/'
        all_papers_uploaded = []
        uploaded = breakdown_rewards[key].get('PAPERS_UPLOADED', [])
        for paper in uploaded:
            paper_url = base_paper_string + '{}/{}'.format(paper[0], paper[1])
            all_papers_uploaded.append(paper_url)

        line = '{},{},{},{},{},{},{},{}\n'.format(
            key,
            total_sorted[key],
            breakdown_rewards[key].get('SUBMITTER_CONTRIBUTIONS') or 0,
            breakdown_rewards[key].get('UPVOTER_CONTRIBUTIONS') or 0,
            breakdown_rewards[key].get('SUBMITTED_UPVOTE_COUNT') or 0,
            breakdown_rewards[key].get('COMMENTER_CONTRIBUTIONS') or 0,
            breakdown_rewards[key].get('UPVOTE_COMMENT_COUNT') or 0,
            "\"" + '\n\n'.join(all_papers_uploaded) + "\""
        )
        headers += line

    text_file = open("rsc_distribution.csv", "w")
    text_file.write(headers)
    text_file.close()
