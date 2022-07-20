import datetime
import math
import os
from datetime import timedelta

import boto3
import pytz
from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from web3 import Web3

from bullet_point.models import BulletPoint
from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as GrmVote
from ethereum.lib import RSC_CONTRACT_ADDRESS, execute_erc20_transfer
from mailing_list.lib import base_email_context
from paper.models import Figure, Paper
from reputation.distributor import RewardDistributor
from reputation.models import Bounty, Contribution, DistributionAmount
from researchhub.celery import (
    QUEUE_BOUNTY_NOTIFICATIONS,
    QUEUE_CONTRIBUTIONS,
    QUEUE_PURCHASES,
    app,
)
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from summary.models import Summary
from utils.message import send_email_message
from utils.sentry import log_info

DEFAULT_REWARD = 1000000


def build_notification_context(message, subject, frontend_view_link):
    return {
        **base_email_context,
        "frontend_view_link": frontend_view_link,
        "message": message,
        "subject": subject,
    }


@periodic_task(
    run_every=crontab(minute="0", hour="10"),
    priority=3,
    queue=QUEUE_BOUNTY_NOTIFICATIONS,
)
def send_bounty_notifications():
    twentynine_days_ago = start_date = datetime.datetime.now() - datetime.timedelta(29)
    bounties = Bounty.objects.filter(
        status=Bounty.OPEN,
        created_date__date=twentynine_days_ago,
    )

    for bounty in bounties:
        content_type = ContentType.objects.get_for_model(bounty)
        action = Action.objects.get(
            user=bounty.created_by,
            content_type=content_type,
            object_id=bounty.id,
        )
        notification = Notification.objects.create(
            recipient=bounty.created_by,
            action_user=bounty.created_by,
            action=action,
            message="Your bounty is expiring in one day! If you have a suitable answer, make sure to pay out your bounty in order to keep your reputation on ResearchHub high.",
        )
        notification.send_notification()
        inner_subject = "Your Bounty is Expiring"
        frontend_view_link = BASE_FRONTEND_URL
        if bounty.item_content_type == ContentType.objects.get_for_model(
            ResearchhubPost
        ):
            frontend_view_link += "/post/{}/{}".format(bounty.item.id, bounty.item.slug)
        context = build_notification_context(
            notification.message, inner_subject, frontend_view_link
        )
        subject = "ResearchHub | Your Bounty is Expiring"
        send_email_message(
            user.email,
            "general_email_message.txt",
            subject,
            context,
            html_template="general_email_message.html",
        )


@app.task(queue=QUEUE_CONTRIBUTIONS)
def create_contribution(
    contribution_type, instance_type, user_id, unified_doc_id, object_id
):
    content_type = ContentType.objects.get(**instance_type)
    if contribution_type == Contribution.SUBMITTER:
        create_author_contribution(
            Contribution.AUTHOR, user_id, unified_doc_id, object_id
        )

    previous_contributions = Contribution.objects.filter(
        contribution_type=contribution_type,
        content_type=content_type,
        unified_document_id=unified_doc_id,
    ).order_by("ordinal")

    ordinal = 0
    if previous_contributions.exists():
        ordinal = previous_contributions.last().ordinal + 1

    Contribution.objects.create(
        contribution_type=contribution_type,
        user_id=user_id,
        ordinal=ordinal,
        unified_document_id=unified_doc_id,
        content_type=content_type,
        object_id=object_id,
    )


@app.task(queue=QUEUE_CONTRIBUTIONS)
def create_author_contribution(contribution_type, user_id, unified_doc_id, object_id):
    contributions = []
    content_type = ContentType.objects.get(model="author")
    authors = ResearchhubUnifiedDocument.objects.get(id=unified_doc_id).authors.all()
    for i, author in enumerate(authors.iterator()):
        if author.user:
            user = author.user
            data = {
                "contribution_type": contribution_type,
                "ordinal": i,
                "unified_document_id": unified_doc_id,
                "content_type": content_type,
                "object_id": object_id,
            }

            if user:
                data["user_id"] = user.id

            contributions.append(Contribution(**data))
    Contribution.objects.bulk_create(contributions)


@app.task(queue=QUEUE_PURCHASES)
def distribute_round_robin(paper_id):
    reward_dis = RewardDistributor()
    paper = Paper.objects.get(id=paper_id)
    items = [
        paper.uploaded_by,
        *paper.authors.all(),
        *paper.votes.all(),
        *paper.threads.all(),
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
        print("{} / {}".format(i, count))
        if user_key in hashes:
            hashes[user_key] += 1
        else:
            hashes[user_key] = 1

        if user_key not in all_users:
            all_users[user_key] = True
    return hashes


def get_action_links(user, reward_amount):
    referral_link = f"https://www.researchhub.com/referral/{user.referral_code}"
    action_links = {
        "twitter": f"https://twitter.com/intent/tweet?url={referral_link}&text=I%27ve%20earned%20{'{:,}'.format(reward_amount)}%20RSC%20this%20week%20on%20ResearchHub%2C%20an%20up%20and%20coming%20collaboration%20platform%20for%20scientists!%20Join%20me%20%26%20help%20contribute%20content%20here%3A%20",
        "facebook": f"https://www.facebook.com/sharer/sharer.php?u={referral_link}",
    }
    return action_links


def get_author_full_name(user):
    author_profile = user.author_profile
    user_name = author_profile.first_name
    if author_profile.last_name:
        user_name += " " + author_profile.last_name
    return user_name


def get_uploaded_papers_email_data(papers_uploaded):
    uploaded_papers = []
    for paper in papers_uploaded:
        paper_data = {}
        paper_data["title"] = paper.title
        paper_data["summary"] = (
            f"From Paper: {paper.summary.summary_plain_text}" if paper.summary else ""
        )
        paper_data["uploaded_by"] = get_author_full_name(paper.uploaded_by)
        paper_data["discussion_count"] = paper.discussion_count
        paper_data["vote_count"] = paper.calculate_score(
            ignore_self_vote=True, ignore_twitter_score=True
        )
        paper_data["paper_type"] = "".join(paper.paper_type.split("_")).capitalize()
        paper_data["url"] = f"{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}"
        paper_preview_list = Figure.objects.filter(
            paper=paper.id, figure_type=Figure.PREVIEW
        ).order_by("created_date")
        if paper_preview_list.exists():
            paper_preview = paper_preview_list.last()
            paper_data["preview"] = paper_preview.file.url
        paper_data["hubs"] = [hub.name for hub in paper.hubs.all()]
        uploaded_papers.append(paper_data)
    return uploaded_papers


def send_distribution_email(user, content_stats):
    context = {
        **base_email_context,
        "user_name": get_author_full_name(user),
        "reward_amount": content_stats["reward_amount"],
        "uploaded_paper_count": content_stats["uploaded_paper_count"],
        "total_paper_votes": content_stats["total_paper_votes"],
        "discussion_count": content_stats["discussion_count"],
        "total_comment_votes": content_stats["total_comment_votes"],
        "total_votes_given": content_stats["total_votes_given"],
        "uploaded_papers": content_stats["uploaded_papers"],
        "action_links": content_stats["action_links"],
    }

    subject = "Notification From ResearchHub"
    send_email_message(
        user.email,
        "distribution_email.txt",
        subject,
        context,
        html_template="distribution_email.html",
    )
