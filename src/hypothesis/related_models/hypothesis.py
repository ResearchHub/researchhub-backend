import datetime

import pytz
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Avg, Count, IntegerField, Q, Sum
from django.db.models.functions import Cast, Extract

from discussion.reaction_models import AbstractGenericReactionModel, Vote
from hypothesis.constants.constants import CITATION_TYPE
from paper.utils import paper_piecewise_log
from purchase.models import Purchase
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User
from utils import sentry


class Hypothesis(AbstractGenericReactionModel):
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="hypothesis",
    )
    authors = models.ManyToManyField(
        "user.Author",
        related_name="authored_hypotheses",
    )
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_hypotheses",
    )
    discussion_count = models.IntegerField(default=0, db_index=True)
    note = models.OneToOneField(
        "note.Note",
        null=True,
        related_name="hypothesis",
        on_delete=models.CASCADE,
    )
    renderable_text = models.TextField(null=True)
    result_score = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    slug = models.SlugField(max_length=1024)
    src = models.FileField(
        blank=True,
        null=True,
        default=None,
        max_length=512,
        upload_to="uploads/hypothesis/%Y/%m/%d/",
    )
    title = models.TextField(blank=True, default="")
    unified_document = models.OneToOneField(
        ResearchhubUnifiedDocument,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="hypothesis",
    )
    purchases = GenericRelation(
        "purchase.Purchase",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="hypothesis",
    )

    def __str__(self):
        return f"{self.__class__}"

    @property
    def users_to_notify(self):
        return [self.created_by]

    @property
    def is_removed(self):
        return self.unified_document.is_removed

    def get_aggregate_citation_consensus(self):
        try:
            citations = self.citations
            result = {"citation_count": citations.count()}

            reject_pile = citations.filter(
                citation_type=CITATION_TYPE["REJECT"]
            ).aggregate(
                down_count=Count("votes", filter=Q(votes__vote_type=Vote.DOWNVOTE)),
                neutral_count=Count("votes", filter=Q(votes__vote_type=Vote.NEUTRAL)),
                up_count=Count("votes", filter=Q(votes__vote_type=Vote.UPVOTE)),
            )

            support_pile = citations.filter(
                citation_type=CITATION_TYPE["SUPPORT"]
            ).aggregate(
                down_count=Count("votes", filter=Q(votes__vote_type=Vote.DOWNVOTE)),
                neutral_count=Count("votes", filter=Q(votes__vote_type=Vote.NEUTRAL)),
                up_count=Count("votes", filter=Q(votes__vote_type=Vote.UPVOTE)),
            )

            # NOTE: down / upvotes counteracting based on citation type ON hypo
            result["down_count"] = reject_pile["up_count"] + support_pile["down_count"]
            result["neutral_count"] = (
                reject_pile["neutral_count"] + support_pile["neutral_count"]
            )
            result["up_count"] = reject_pile["down_count"] + support_pile["up_count"]
            return result

        except Exception as error:
            sentry.log_error(error)
            return {"citation_count": 0, "down_count": 0, "up_count": 0}

    def get_accepted_answer(self):
        return self.threads.filter(
            is_accepted_answer=True, discussion_post_type="ANSWER"
        ).first()

    def get_boost_amount(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID, amount__gt=0, boost_time__gt=0
        )
        if purchases.exists():
            boost_amount = (
                purchases.annotate(amount_as_int=Cast("amount", IntegerField()))
                .aggregate(sum=Sum("amount_as_int"))
                .get("sum", 0)
            )
            return boost_amount
        return 0

    def get_discussion_count(self):
        thread_count = self.threads.aggregate(
            discussion_count=Count(
                1,
                filter=Q(
                    is_removed=False,
                    created_by__isnull=False,
                ),
            )
        )["discussion_count"]
        comment_count = self.threads.aggregate(
            discussion_count=Count(
                "comments",
                filter=Q(
                    comments__is_removed=False,
                    comments__created_by__isnull=False,
                ),
            )
        )["discussion_count"]
        reply_count = self.threads.aggregate(
            discussion_count=Count(
                "comments__replies",
                filter=Q(
                    comments__replies__is_removed=False,
                    comments__replies__created_by__isnull=False,
                ),
            )
        )["discussion_count"]
        return thread_count + comment_count + reply_count

    def calculate_hot_score(self):
        ALGO_START_UNIX = 1546329600
        TIME_DIV = 3600000
        HOUR_SECONDS = 86400
        DATE_BOOST = 11

        boosts = self.purchases.filter(
            paid_status=Purchase.PAID,
            amount__gt=0,
            user__moderator=True,
            boost_time__gte=0,
        )

        today = datetime.datetime.now(tz=pytz.utc).replace(hour=0, minute=0, second=0)
        score = self.score
        original_uploaded_date = self.created_date
        uploaded_date = original_uploaded_date
        day_delta = datetime.timedelta(days=2)
        timeframe = today - day_delta

        if original_uploaded_date > timeframe:
            uploaded_date = timeframe.replace(
                hour=original_uploaded_date.hour,
                minute=original_uploaded_date.minute,
                second=original_uploaded_date.second,
            )

        votes = self.votes
        if votes.exists():
            vote_avg_epoch = (
                self.votes.aggregate(
                    avg=Avg(
                        Extract("created_date", "epoch"),
                        output_field=models.IntegerField(),
                    )
                )["avg"]
                or 0
            )
            num_votes = votes.count()
        else:
            num_votes = 0
            vote_avg_epoch = timeframe.timestamp()

        vote_avg = (max(0, vote_avg_epoch - ALGO_START_UNIX)) / TIME_DIV

        base_score = paper_piecewise_log(score + 1)
        uploaded_date_score = uploaded_date.timestamp() / TIME_DIV
        vote_score = paper_piecewise_log(num_votes + 1)
        discussion_score = paper_piecewise_log(self.discussion_count + 1)

        if original_uploaded_date > timeframe:
            uploaded_date_delta = original_uploaded_date - timeframe
            delta_days = paper_piecewise_log(
                uploaded_date_delta.total_seconds() / HOUR_SECONDS
            )
            delta_days *= DATE_BOOST
            uploaded_date_score += delta_days
        else:
            uploaded_date_delta = timeframe - original_uploaded_date
            delta_days = -paper_piecewise_log(
                (uploaded_date_delta.total_seconds() / HOUR_SECONDS) + 1
            )
            delta_days *= DATE_BOOST
            uploaded_date_score += delta_days

        boost_score = 0
        if boosts.exists():
            boost_amount = sum(map(int, boosts.values_list("amount", flat=True)))
            boost_score = paper_piecewise_log(boost_amount + 1)

        hot_score = (
            base_score
            + uploaded_date_score
            + vote_avg
            + vote_score
            + discussion_score
            + boost_score
        ) * 1000

        return hot_score

    def get_promoted_score(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID, amount__gt=0, boost_time__gt=0
        )
        if purchases.exists():
            base_score = self.score
            boost_amount = (
                purchases.annotate(amount_as_int=Cast("amount", IntegerField()))
                .aggregate(sum=Sum("amount_as_int"))
                .get("sum", 0)
            )
            return base_score + boost_amount
        return False
