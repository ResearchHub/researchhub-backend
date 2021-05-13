import math
import datetime
import pytz

from django.db import transaction
from django.db.models import Q, F

from django.contrib.contenttypes.models import ContentType
from datetime import timedelta
from django.utils import timezone

from researchhub.settings import BASE_FRONTEND_URL
from researchhub.celery import app
from paper.models import Paper, Vote as PaperVote, Figure
from discussion.models import Thread, Reply, Comment
from bullet_point.models import BulletPoint
from summary.models import Summary
from reputation.models import Contribution, DistributionAmount
from reputation.distributor import RewardDistributor
from utils.sentry import log_info
from utils.message import send_email_message
from mailing_list.lib import base_email_context

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


def distribute_rewards(starting_date=None, end_date=None, distribute=True):
    from user.models import User

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
        ),
        paper__uploaded_by=F('created_by')
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
        vote_created_by = obj.created_by.email

        if user_key == vote_created_by:
            continue

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

    bulletpoints = BulletPoint.objects.filter(
        created_by__probable_spammer=False,
        created_by__is_suspended=False,
        created_date__gt=starting_date,
        created_date__lte=end_date,
    )

    summaries = Summary.objects.filter(
        proposed_by__probable_spammer=False,
        proposed_by__is_suspended=False,
        created_date__gt=starting_date,
        created_date__lte=end_date,
    )

    comment_votes_count = {}
    comment_upvotes_count = {}
    bulletpoint_votes_count = {}
    bulletpoint_upvotes_count = {}
    summary_votes_count = {}
    summary_upvotes_count = {}

    count = threads.count()
    comment_score = 0
    for i, obj in enumerate(threads):
        print('{} / {}'.format(i, count))
        score = obj.calculate_score(ignore_self_vote=True)
        comment_score += score
        user_key = obj.created_by.email
        if user_key in IGNORE_USERS:
            continue
        if user_key in comment_votes_count:
            comment_votes_count[user_key] += score
        else:
            comment_votes_count[user_key] = score

        for vote in obj.votes.exclude(created_by=obj.created_by):
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
        score = obj.calculate_score(ignore_self_vote=True)
        comment_score += score
        user_key = obj.created_by.email
        if user_key in IGNORE_USERS:
            continue
        if user_key in comment_votes_count:
            comment_votes_count[user_key] += score
        else:
            comment_votes_count[user_key] = score

        for vote in obj.votes.exclude(created_by=obj.created_by):
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
        score = obj.calculate_score(ignore_self_vote=True)
        comment_score += score
        user_key = obj.created_by.email
        if user_key in IGNORE_USERS:
            continue
        if user_key in comment_votes_count:
            comment_votes_count[user_key] += score
        else:
            comment_votes_count[user_key] = score

        for vote in obj.votes.exclude(created_by=obj.created_by):
            total_score += 1
            user_upvote_key = vote.created_by.email
            if user_upvote_key in comment_upvotes_count:
                comment_upvotes_count[user_upvote_key] += 1
            else:
                comment_upvotes_count[user_upvote_key] = 1

        if user_key not in all_users:
            all_users[user_key] = True

    count = bulletpoints.count()
    bulletpoint_score = 0
    for i, obj in enumerate(bulletpoints):
        print('{} / {}'.format(i, count))
        user_key = obj.created_by.email
        score = obj.calculate_score(ignore_self_vote=True)
        bulletpoint_score += score
        if user_key in IGNORE_USERS:
            continue
        if user_key in bulletpoint_votes_count:
            bulletpoint_votes_count[user_key] += score
        else:
            bulletpoint_votes_count[user_key] = score

        for vote in obj.votes.exclude(bulletpoint__created_by=F('created_by')):
            total_score += 1
            user_upvote_key = vote.created_by.email
            if user_upvote_key in bulletpoint_upvotes_count:
                bulletpoint_upvotes_count[user_upvote_key] += 1
            else:
                bulletpoint_upvotes_count[user_upvote_key] = 1

        if user_key not in all_users:
            all_users[user_key] = True

    count = summaries.count()
    summary_score = 0
    for i, obj in enumerate(summaries):
        print('{} / {}'.format(i, count))
        user_key = obj.proposed_by.email
        score = obj.calculate_score(ignore_self_vote=True)
        summary_score += score
        if user_key in IGNORE_USERS:
            continue
        if user_key in summary_votes_count:
            summary_votes_count[user_key] += score
        else:
            summary_votes_count[user_key] = score

        for vote in obj.votes.exclude(summary__proposed_by=F('created_by')):
            total_score += 1
            user_upvote_key = vote.created_by.email
            if user_upvote_key in summary_upvotes_count:
                summary_upvotes_count[user_upvote_key] += 1
            else:
                summary_upvotes_count[user_upvote_key] = 1

        if user_key not in all_users:
            all_users[user_key] = True

    # headers = 'Total Upvotes: {}, Total Paper Upvotes: {}, Total Comment Upvotes: {}\n'.format(total_score, total_paper_scores, total_comment_scores,)
    headers = 'name,email,Author URL,Bonus RSC Amount,Paper Submissions,Upvotes,Upvotes on Submissions,Comments,Upvotes on Comments,Key Takeaway Upvotes,Upvotes on Key Takeaways,Upvotes on Summary,Summary Upvotes,Papers Uploaded\n'

    total_rewards = {}

    for key in all_users:
        with transaction.atomic():
            upload_vote_count = paper_voted_on_count.get(key, 0)
            comment_vote_count = comment_votes_count.get(key, 0)
            bulletpoint_vote_count = bulletpoint_votes_count.get(key, 0)
            summary_vote_count = summary_votes_count.get(key, 0)

            vote_count = upload_vote_count + comment_vote_count + bulletpoint_vote_count + summary_vote_count

            upvotes_count = (
                paper_votes_count.get(key, 0) +
                comment_upvotes_count.get(key, 0) +
                bulletpoint_upvotes_count.get(key, 0) +
                summary_upvotes_count.get(key, 0)
            )
            upvoted_amount = math.floor((vote_count / (total_score)) * score_reward_amount)
            upvotes_amount = math.floor(upvotes_count / total_score * upvote_reward_amount)
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
                    distribute=distribute
                )
                user = User.objects.get(email=key)
                papers = papers_uploaded.filter(uploaded_by__email=key)
                uploaded_papers_email_data = get_uploaded_papers_email_data(papers)
                action_links = get_action_links(user, reward_amount)
                content_stats = {
                    'reward_amount': reward_amount,
                    'uploaded_paper_count': uploaded_paper_count.get(key, 0),
                    'total_paper_votes': upvotes_count,
                    'discussion_count': comment_vote_count,
                    'total_comment_votes': comment_upvotes_count.get(key, 0),
                    'total_votes_given': upload_vote_count,
                    'uploaded_papers': uploaded_papers_email_data,
                    'action_links': action_links,
                }
                send_distribution_email(user, content_stats)

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
        line = '{},{},{},{},{},{},{},{},{},{},{},{},{},{}\n'.format(
            name,
            user.email,
            author_url,
            total_sorted[key],
            uploaded_paper_count.get(key, 0),
            paper_votes_count.get(key, 0),
            paper_voted_on_count.get(key, 0),
            discussion_count.get(key, 0),
            comment_votes_count.get(key, 0),
            bulletpoint_upvotes_count.get(key, 0),
            bulletpoint_votes_count.get(key, 0),
            summary_votes_count.get(key, 0),
            summary_upvotes_count.get(key, 0),
            "\"" + '\n\n'.join(papers_list) + "\""
        )
        headers += line

    text_file = open("rsc_distribution.csv", "w")
    text_file.write(headers)
    text_file.close()


def get_action_links(user, reward_amount):
    referral_link = f'https://www.researchhub.com/referral/{user.referral_code}'
    action_links = {
        'twitter': f"https://twitter.com/intent/tweet?url={referral_link}&text=I%27ve%20earned%20{'{:,}'.format(reward_amount)}%20RSC%20this%20week%20on%20ResearchHub%2C%20an%20up%20and%20coming%20collaboration%20platform%20for%20scientists!%20Join%20me%20%26%20help%20contribute%20content%20here%3A%20",
        'facebook': f'https://www.facebook.com/sharer/sharer.php?u={referral_link}',
    }
    return action_links


def get_author_full_name(user):
    author_profile = user.author_profile
    user_name = author_profile.first_name
    if author_profile.last_name:
        user_name += ' ' + author_profile.last_name
    return user_name


def get_uploaded_papers_email_data(papers_uploaded):
    uploaded_papers = []
    for paper in papers_uploaded:
        paper_data = {}
        paper_data['title'] = paper.title
        paper_data['summary'] = f'From Paper: {paper.summary.summary_plain_text}' if paper.summary else ''
        paper_data['uploaded_by'] = get_author_full_name(paper.uploaded_by)
        paper_data['discussion_count'] = paper.discussion_count
        paper_data['vote_count'] = paper.calculate_score(ignore_self_vote=True, ignore_twitter_score=True)
        paper_data['paper_type'] = ''.join(paper.paper_type.split('_')).capitalize()
        paper_data['url'] = f'{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}'
        paper_preview_list = Figure.objects.filter(paper=paper.id, figure_type=Figure.PREVIEW).order_by('created_date')
        if paper_preview_list.exists():
            paper_preview = paper_preview_list.last()
            paper_data['preview'] = paper_preview.file.url
        paper_data['hubs'] = [hub.name for hub in paper.hubs.all()]
        uploaded_papers.append(paper_data)
    return uploaded_papers


def send_distribution_email(user, content_stats):
    context = {
        **base_email_context,
        'user_name': get_author_full_name(user),
        'reward_amount': content_stats['reward_amount'],
        'uploaded_paper_count': content_stats['uploaded_paper_count'],
        'total_paper_votes': content_stats['total_paper_votes'],
        'discussion_count': content_stats['discussion_count'],
        'total_comment_votes': content_stats['total_comment_votes'],
        'total_votes_given': content_stats['total_votes_given'],
        'uploaded_papers': content_stats['uploaded_papers'],
        'action_links': content_stats['action_links'],
    }

    subject = 'Notification From ResearchHub'
    send_email_message(
        user.email,
        'distribution_email.txt',
        subject,
        context,
        html_template='distribution_email.html'
    )
