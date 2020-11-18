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


@periodic_task(
    run_every=REWARD_SCHEDULE,
    priority=3,
    options={'queue': APP_ENV}
)
def distribute_rewards(starting_date=None, end_date=None, distribute=True):
    from user.models import User
    
    return True
    if end_date is None:
        end_date = datetime.datetime.now(tz=pytz.utc)

    # static_start_date = datetime.datetime(
    #     year=2020,
    #     month=10,
    #     day=29,
    #     hour=0,
    #     minute=0,
    # )
    # static_end_date = datetime.datetime(
    #     year=2020,
    #     month=11,
    #     day=8,
    #     hour=23,
    #     minute=59,
    # )

    # Checks if rewards should be distributed, given time config
    reward_time_hour, reward_time_day, reward_time_week = list(
        map(int, REWARD_TIME.split(' '))
    )

    if reward_time_week:
        week = end_date.isocalendar()[1]
        if week % reward_time_week != 0:
            return
        # time_delta = datetime.timedelta(weeks=reward_time_week)
    elif reward_time_day:
        day = end_date.day
        if day % reward_time_day != 0:
            return
        # time_delta = datetime.timedelta(days=reward_time_day)
    elif reward_time_hour:
        hour = end_date.hour
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
    if last_distributed.exists() and starting_date is not None:
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
        'mcburniewill@gmail.com',
        'younggarrett210@gmail.com'
    )

    all_users = {}
    all_papers_uploaded = {}
    papers_uploaded = Paper.objects.filter(
        is_removed=False,
        uploaded_by__probable_spammer=False,
        uploaded_by__is_suspended=False,
        uploaded_date__gt=starting_date,
        uploaded_date__lte=end_date,
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
        created_date__lte=end_date,
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
    total_paper_scores = 0
    for i, obj in enumerate(paper_votes):
        print('{} / {}'.format(i, count))
        score = 1
        if obj.vote_type == 1:
            score = 1
        else:
            score = -1

        if not obj.paper.uploaded_by or obj.paper.uploaded_by.email in IGNORE_USERS:
            continue

        total_score += score
        total_paper_scores += score
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
        created_date__lte=end_date,
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
        created_date__lte=end_date,
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
        created_date__lte=end_date,
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
        user_key = obj.created_by.email
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

    total_comment_scores = comment_score
    # headers = 'Total Upvotes: {}, Total Paper Upvotes: {}, Total Comment Upvotes: {}\n'.format(total_score, total_paper_scores, total_comment_scores,)
    headers = 'email,name,Author URL,Bonus RSC Amount,Paper Submissions,Upvotes,Upvotes on Submissions,Comments,Upvotes on Comments,Papers Uploaded\n'

    total_rewards = {}

    for key in all_users:
        upload_vote_count = paper_voted_on_count.get(key, 0)
        comment_upvote_count = comment_votes_count.get(key, 0)
        votes_count = paper_votes_count.get(key, 0) + comment_upvotes_count.get(key, 0)
        upvoted_amount = math.floor(((upload_vote_count + comment_upvote_count) / (total_score)) * score_reward_amount)
        upvotes_amount = math.floor(votes_count / total_score * upvote_reward_amount)
        reward_amount = upvoted_amount + upvotes_amount

        total_rewards[key] = reward_amount
        if distribute:
            item = Contribution.objects.filter(user__email=key)
            if not item.exists():
                item = User.objects.get(email=key)
            else:
                item = item.last()
            reward_dis.generate_distribution(
                item,
                amount=reward_amount,
                distribute=True
            )

    if distribute:
        last_distribution.distributed = True
        last_distribution.save()

    total_sorted = {k: v for k, v in sorted(total_rewards.items(), key=lambda item: item[1], reverse=True)}
    for key in total_sorted:

        base_paper_string = 'https://www.researchhub.com/paper/'
        papers_list = []
        uploaded = all_papers_uploaded.get(key, [])
        for paper in uploaded:
            paper_url = base_paper_string + '{}/{}'.format(paper[0], paper[1])
            papers_list.append(paper_url)

        user = User.objects.get(email=key)
        author_profile = user.author_profile
        name = author_profile.first_name + ' ' + author_profile.last_name
        author_url = 'https://www.researchhub.com/user/{}'.format(author_profile.id)
        line = '{},{},{},{},{},{},{},{},{},{}\n'.format(
            user.email,
            name,
            author_url,
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
