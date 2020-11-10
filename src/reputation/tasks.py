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
from paper.models import Paper, Vote as PaperVote
from discussion.models import Vote as DiscussionVote, Thread, Reply, Comment
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

def set_or_increment(queryset, hashes, all_users, attributes):
    count = queryset.count()
    for i, obj in enumerate(queryset):
        user_key = obj

        for attribute in attributes:
            user_key = getattr(user_key, attribute)
        print('{} / {}'.format(i, count))
        if user_key in hashes:
            hashes[user_key] += 1
        else:
            hashes[user_key] = 1
        
        if user_key not in all_users:
            all_users[user_key] = True
    return hashes

def new_reward_calculation(distribute):
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

    score_reward_amount = total_reward_amount * .95
    upvote_reward_amount = total_reward_amount - score_reward_amount
    IGNORE_USERS = (
        'pdj7@georgetown.edu',
        'lightning.lu7@gmail.com',
        'barmstrong@gmail.com',
    )

    all_users = {}
    all_papers_uploaded = {}
    papers_uploaded = Paper.objects.filter(
        is_removed=False,
        uploaded_by__probable_spammer=False,
        uploaded_by__is_suspended=False,
        uploaded_date__gt=starting_date,
        uploaded_date__lte=static_date,
    ).exclude(
        Q(
            uploaded_by__email__in=IGNORE_USERS
        )
    )

    count = papers_uploaded.count()
    for i, obj in enumerate(papers_uploaded):
        print('{} / {}'.format(i, count))
        paper = (obj.id, obj.slug)
        if not obj.uploaded_by or obj.uploaded_by.email in IGNORE_USERS:
            continue
        user_key = obj.uploaded_by.email
        if user_key in all_papers_uploaded:
            all_papers_uploaded[user_key].append(paper)
        else:
            all_papers_uploaded[user_key] = [paper]
        
        if user_key not in all_users:
            all_users[user_key] = True
    uploaded_paper_count = {}
    set_or_increment(papers_uploaded, uploaded_paper_count, all_users, ['uploaded_by', 'email'])

    paper_votes = PaperVote.objects.filter(
        paper__is_removed=False,
        created_by__probable_spammer=False,
        created_by__is_suspended=False,
        created_date__gt=starting_date,
        created_date__lte=static_date,
    ).exclude(
        Q(
            created_by__email__in=IGNORE_USERS
        )
    )
    paper_votes_count = {}
    set_or_increment(paper_votes, paper_votes_count, all_users, ['created_by', 'email'])

    paper_voted_on_count = {}

    count = paper_votes.count()
    total_score = 0
    for i, obj in enumerate(paper_votes):
        print('{} / {}'.format(i, count))
        score = 1
        if obj.vote_type == 1:
            score = 1
        else:
            score = -1

        total_score += score
        if not obj.paper.uploaded_by or obj.paper.uploaded_by.email in IGNORE_USERS:
            continue
        user_key = obj.paper.uploaded_by.email
        if user_key in paper_voted_on_count:
            paper_voted_on_count[user_key] += score
        else:
            paper_voted_on_count[user_key] = score
        
        if user_key not in all_users:
            all_users[user_key] = True
    
    threads = Thread.objects.filter(
        is_removed=False,
        paper__is_removed=False,
        created_by__probable_spammer=False,
        created_by__is_suspended=False,
        created_date__gt=starting_date,
        created_date__lte=static_date,
    ).exclude(
        Q(
            created_by__email__in=IGNORE_USERS
        )
    )
    discussion_count = {}
    set_or_increment(threads, discussion_count, all_users, ['created_by', 'email'])

    comments = Comment.objects.filter(
        is_removed=False,
        parent__is_removed=False,
        parent__paper__is_removed=False,
        created_by__probable_spammer=False,
        created_by__is_suspended=False,
        created_date__gt=starting_date,
        created_date__lte=static_date,
    ).exclude(
        Q(
            created_by__email__in=IGNORE_USERS
        )
    )
    set_or_increment(comments, discussion_count, all_users, ['created_by', 'email'])

    replies = Reply.objects.filter(
        is_removed=False,
        created_by__probable_spammer=False,
        created_by__is_suspended=False,
        created_date__gt=starting_date,
        created_date__lte=static_date,
    ).exclude(
        Q(
            created_by__email__in=IGNORE_USERS
        )
    )
    set_or_increment(replies, discussion_count, all_users, ['created_by', 'email'])

    comment_votes_count = {}
    comment_upvotes_count = {}
    count = threads.count()
    comment_score = 0
    for i, obj in enumerate(threads):
        print('{} / {}'.format(i, count))
        score = obj.calculate_score()
        comment_score += score
        user_key = obj.created_by.email
        if user_key in IGNORE_USERS:
            continue
        if user_key in comment_votes_count:
            comment_votes_count[user_key] += score
        else:
            comment_votes_count[user_key] = score

        for vote in obj.votes.all():
            total_score += 1
            user_upvote_key = vote.created_by.email
            if user_upvote_key in comment_upvotes_count:
                comment_upvotes_count[user_upvote_key] += 1
            else:
                comment_upvotes_count[user_upvote_key] = 1
        if user_key not in all_users:
            all_users[user_key] = True

    count = replies.count()
    for i, obj in enumerate(replies):
        print('{} / {}'.format(i, count))
        score = obj.calculate_score()
        comment_score += score
        user_key = replies.created_by.email
        if user_key in IGNORE_USERS:
            continue
        if user_key in comment_votes_count:
            comment_votes_count[user_key] += score
        else:
            comment_votes_count[user_key] = score
        
        for vote in obj.votes.all():
            user_upvote_key = vote.created_by.email
            total_score += 1
            if user_upvote_key in comment_upvotes_count:
                comment_upvotes_count[user_upvote_key] += 1
            else:
                comment_upvotes_count[user_upvote_key] = 1
        
        if user_key not in all_users:
            all_users[user_key] = True

    count = comments.count()
    for i, obj in enumerate(comments):
        print('{} / {}'.format(i, count))
        score = obj.calculate_score()
        comment_score += score
        user_key = comments.created_by.email
        if user_key in IGNORE_USERS:
            continue
        if user_key in comment_votes_count:
            comment_votes_count[user_key] += score
        else:
            comment_votes_count[user_key] = score
        
        for vote in obj.votes.all():
            total_score += 1
            user_upvote_key = vote.created_by.email
            if user_upvote_key in comment_upvotes_count:
                comment_upvotes_count[user_upvote_key] += 1
            else:
                comment_upvotes_count[user_upvote_key] = 1
        
        if user_key not in all_users:
            all_users[user_key] = True

    # total_count = uploaded_.count()
    total_paper_scores = paper_votes.filter(vote_type=1).count()
    total_comment_scores = comment_score
    headers = 'Total Upvotes: {}, Total Paper Upvotes: {}, Total Comment Upvotes: {}\n'.format(total_paper_scores + total_comment_scores, total_paper_scores, total_comment_scores,)
    headers += 'email,Bonus RSC Amount,Paper Submissions,Upvotes,Upvotes on Submissions,Comments,Upvotes on Comments,Papers Uploaded\n'

    total_rewards = {}
    total_comment_count = (threads.count() + replies.count() + comments.count()) or 1

    for key in all_users:
        upload_vote_count = paper_voted_on_count.get(key, 0)
        comment_upvote_count = comment_votes_count.get(key, 0)
        votes_count = paper_votes_count.get(key, 0) + comment_upvotes_count.get(key, 0)
        upvoted_amount = math.floor(((upload_vote_count + comment_upvote_count) / (total_paper_scores + total_comment_scores)) * score_reward_amount)
        upvotes_amount = math.floor(votes_count / total_score * upvote_reward_amount)

        total_rewards[key] = upvoted_amount + upvotes_amount

    total_sorted = {k: v for k, v in sorted(total_rewards.items(), key=lambda item: item[1], reverse=True)}
    for key in total_sorted:

        base_paper_string = 'https://www.researchhub.com/paper/'
        papers_list = []
        uploaded = all_papers_uploaded.get(key, [])
        for paper in uploaded:
            paper_url = base_paper_string + '{}/{}'.format(paper[0], paper[1])
            papers_list.append(paper_url)

        line = '{},{},{},{},{},{},{},{}\n'.format(
            key,
            total_sorted[key],
            uploaded_paper_count.get(key, 0),
            paper_votes_count.get(key, 0),
            paper_voted_on_count.get(key, 0),
            discussion_count.get(key, 0),
            comment_votes_count.get(key, 0),
            "\"" + '\n\n'.join(papers_list) + "\""
        )
        headers += line

    text_file = open("rsc_distribution.csv", "w")
    text_file.write(headers)
    text_file.close()
