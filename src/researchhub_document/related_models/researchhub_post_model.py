import datetime

import pytz
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Avg, Count, IntegerField, Q, Sum
from django.db.models.functions import Cast, Extract

from discussion.reaction_models import AbstractGenericReactionModel, Vote
from hub.serializers import HubSerializer
from paper.utils import paper_piecewise_log
from purchase.models import Purchase
from researchhub_comment.models import RhCommentThreadModel
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    DOCUMENT_TYPES,
)
from researchhub_document.related_models.constants.editor_type import (
    CK_EDITOR,
    EDITOR_TYPES,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import Author, User


class ResearchhubPost(AbstractGenericReactionModel):
    authors = models.ManyToManyField(
        Author,
        related_name="authored_posts",
    )
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_posts",
    )
    discussion_count = models.IntegerField(default=0, db_index=True)
    discussion_src = models.FileField(
        blank=True,
        default=None,
        max_length=512,
        null=True,
        upload_to="uploads/post_discussion/%Y/%m/%d/",
    )
    document_type = models.CharField(
        choices=DOCUMENT_TYPES,
        default=DISCUSSION,
        max_length=32,
        null=False,
    )
    editor_type = models.CharField(
        choices=EDITOR_TYPES,
        default=CK_EDITOR,
        max_length=32,
        help_text="Editor used to compose the post",
    )
    eln_src = models.FileField(
        blank=True,
        default=None,
        max_length=512,
        null=True,
        upload_to="uploads/post_eln/%Y/%m/%d/",
    )
    note = models.OneToOneField(
        "note.Note",
        null=True,
        related_name="post",
        on_delete=models.CASCADE,
    )
    prev_version = models.OneToOneField(
        "self",
        blank=True,
        default=None,
        null=True,
        on_delete=models.SET_NULL,
        related_name="next_version",
    )
    preview_img = models.URLField(
        blank=True,
        default=None,
        null=True,
    )
    renderable_text = models.TextField(
        blank=True,
        default="",
    )
    rh_threads = GenericRelation(
        RhCommentThreadModel,
        help_text="New Comment-Thread module as of Jan 2023",
        related_query_name="rh_post",
    )
    bounty_type = models.CharField(blank=True, null=True, max_length=64)
    title = models.TextField(blank=True, default="")
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        db_index=True,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    version_number = models.IntegerField(
        blank=False,
        default=1,
        null=False,
    )
    purchases = GenericRelation(
        "purchase.Purchase",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="post",
    )
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="posts",
    )
    # This is already inherited from the base class
    # but is required to set the related lookup name
    votes = GenericRelation(Vote, related_query_name="related_post")
    slug = models.SlugField(max_length=1024)
    doi = models.CharField(
        max_length=255, default=None, null=True, blank=True, unique=True
    )

    @property
    def has_accepted_answer(self):
        return self.get_accepted_answer() is not None

    @property
    def is_latest_version(self):
        return self.next_version is None

    @property
    def is_root_version(self):
        return self.version_number == 1

    @property
    def users_to_notify(self):
        return [self.created_by]

    @property
    def paper(self):
        return None

    @property
    def hubs(self):
        return self.unified_document.hubs

    @property
    def is_removed(self):
        return self.unified_document.is_removed

    @property
    def hot_score(self):
        return self.unified_document.hot_score

    @property
    def hubs_indexing(self):
        return [HubSerializer(h).data for h in self.hubs.all()]

    @property
    def hubs_indexing_flat(self):
        return [hub.name for hub in self.hubs.all()]

    @property
    def hot_score_indexing(self):
        return self.unified_document.hot_score

    @property
    def authors_indexing(self):
        authors = []

        for author in self.unified_document.authors:
            authors.append(
                {
                    "first_name": author.first_name,
                    "last_name": author.last_name,
                    "full_name": author.full_name,
                }
            )

        return authors

    def get_document_slug_type(self):
        if self.document_type == "BOUNTY":
            return "bounty"
        elif self.document_type == "DISCUSSION":
            return "post"
        elif self.document_type == "QUESTION":
            return "question"

        return "post"

    # Used for analytics such as Amazon Personalize
    def get_analytics_type(self):
        return "post"

    # Used for analytics such as Amazon Personalize
    def get_analytics_id(self):
        return self.get_analytics_type() + "_" + str(self.id)

    def get_accepted_answer(self):
        return self.threads.filter(
            is_accepted_answer=True, discussion_post_type="ANSWER"
        ).first()

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

    def get_full_markdown(self):
        try:
            if self.document_type == DISCUSSION:
                byte_string = self.discussion_src.read()
            else:
                byte_string = self.eln_src.read()
            full_markdown = byte_string.decode("utf-8")
            return full_markdown
        except Exception as e:
            print(e)
            return None

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
        original_created_date = self.created_date
        created_date = original_created_date
        day_delta = datetime.timedelta(days=2)
        timeframe = today - day_delta

        if original_created_date > timeframe:
            created_date = timeframe.replace(
                hour=original_created_date.hour,
                minute=original_created_date.minute,
                second=original_created_date.second,
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
        created_date_score = created_date.timestamp() / TIME_DIV
        vote_score = paper_piecewise_log(num_votes + 1)
        discussion_score = paper_piecewise_log(self.discussion_count + 1)

        if original_created_date > timeframe:
            created_date_delta = original_created_date - timeframe
            delta_days = paper_piecewise_log(
                created_date_delta.total_seconds() / HOUR_SECONDS
            )
            delta_days *= DATE_BOOST
            created_date_score += delta_days
        else:
            created_date_delta = timeframe - original_created_date
            delta_days = -paper_piecewise_log(
                (created_date_delta.total_seconds() / HOUR_SECONDS) + 1
            )
            delta_days *= DATE_BOOST
            created_date_score += delta_days

        boost_score = 0
        if boosts.exists():
            boost_amount = sum(map(int, boosts.values_list("amount", flat=True)))
            boost_score = paper_piecewise_log(boost_amount + 1)

        hot_score = (
            base_score
            + created_date_score
            + vote_avg
            + vote_score
            + discussion_score
            + boost_score
        ) * 1000

        return hot_score
