from datetime import datetime, timedelta
from statistics import mean

import pytz
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from hub.models import Hub
from reputation.models import Bounty
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.models import Permission
from researchhub_document.hot_score_mixin import HotScoreMixin
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    DOCUMENT_TYPES,
    FILTER_ALL,
    FILTER_ANSWERED,
    FILTER_AUTHOR_CLAIMED,
    FILTER_BOUNTY_CLOSED,
    FILTER_BOUNTY_EXPIRED,
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    FILTER_OPEN_ACCESS,
    FILTER_PEER_REVIEWED,
    HYPOTHESIS,
    NOTE,
    PAPER,
    QUESTION,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
    SORT_DISCUSSED,
    SORT_UPVOTED,
)
from researchhub_document.tasks import update_elastic_registry
from user.models import Author
from utils.models import DefaultModel
from utils.sentry import log_error


class DocumentFilter(DefaultModel):
    # Filter Fields
    answered = models.BooleanField(default=False, db_index=True)
    author_claimed = models.BooleanField(default=False, db_index=True)
    bounty_closed = models.BooleanField(default=False, db_index=True)
    bounty_expired = models.BooleanField(default=False, db_index=True)
    bounty_open = models.BooleanField(default=False, db_index=True)
    has_bounty = models.BooleanField(default=False, db_index=True)
    open_access = models.BooleanField(default=False, db_index=True)
    peer_reviewed = models.BooleanField(default=False, db_index=True)

    # Sorting Fields
    bounty_expiration_date = models.DateTimeField(null=True)
    bounty_total_amount = models.DecimalField(
        decimal_places=10, max_digits=19, null=True, db_index=True
    )

    discussed_today = models.IntegerField(default=0, db_index=True)
    discussed_week = models.IntegerField(default=0, db_index=True)
    discussed_month = models.IntegerField(default=0, db_index=True)
    discussed_all = models.IntegerField(default=0, db_index=True)
    discussed_date = models.DateTimeField(auto_now_add=True)

    # discussed_today_date = models.DateTimeField(auto_now_add=True)
    # discussed_week_date = models.DateTimeField(auto_now_add=True)
    # discussed_month_date = models.DateTimeField(auto_now_add=True)
    # discussed_year_date = models.DateTimeField(auto_now_add=True)
    # discussed_all_date = models.DateTimeField(auto_now_add=True)

    upvoted_today = models.IntegerField(default=0, db_index=True)
    upvoted_week = models.IntegerField(default=0, db_index=True)
    upvoted_month = models.IntegerField(default=0, db_index=True)
    upvoted_all = models.IntegerField(default=0, db_index=True)
    upvoted_date = models.DateTimeField(auto_now_add=True)

    # upvoted_today_date = models.DateTimeField(auto_now_add=True)
    # upvoted_week_date = models.DateTimeField(auto_now_add=True)
    # upvoted_month_date = models.DateTimeField(auto_now_add=True)
    # upvoted_year_date = models.DateTimeField(auto_now_add=True)
    # upvoted_all_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = (
            models.Index(
                fields=("created_date",),
                name="flt_created_date_idx",
            ),
            models.Index(
                fields=("bounty_expiration_date",),
                name="flt_bounty_expiration_date_idx",
            ),
            models.Index(
                fields=("discussed_date",),
                name="flt_discussed_date_idx",
            ),
            # models.Index(
            #     fields=("discussed_today_date",),
            #     name="flt_discussed_today_date_idx",
            # ),
            # models.Index(
            #     fields=("discussed_week_date",),
            #     name="flt_discussed_week_date_idx",
            # ),
            # models.Index(
            #     fields=("discussed_month_date",),
            #     name="flt_discussed_month_date_idx",
            # ),
            # models.Index(
            #     fields=("discussed_year_date",),
            #     name="flt_discussed_year_date_idx",
            # ),
            # models.Index(
            #     fields=("discussed_all_date",),
            #     name="flt_discussed_all_date_idx",
            # ),
            # models.Index(
            #     fields=("upvoted_today_date",),
            #     name="flt_upvoted_today_date_idx",
            # ),
            # models.Index(
            #     fields=("upvoted_week_date",),
            #     name="flt_upvoted_week_date_idx",
            # ),
            # models.Index(
            #     fields=("upvoted_month_date",),
            #     name="flt_upvoted_month_date_idx",
            # ),
            # models.Index(
            #     fields=("upvoted_year_date",),
            #     name="flt_upvoted_year_date_idx",
            # ),
            # models.Index(
            #     fields=("upvoted_all_date",),
            #     name="flt_upvoted_all_date_idx",
            # ),
            models.Index(
                fields=("upvoted_date",),
                name="flt_upvoted_date_idx",
            ),
        )

    def update_filters(self, update_types):
        for update_type in update_types:
            self.update_filter(update_type)

    def update_filter(self, update_type=FILTER_ALL):
        unified_document = self.unified_document
        document_type = unified_document.document_type
        document = unified_document.get_document()

        updates = []
        if document_type == PAPER:
            if update_type == FILTER_AUTHOR_CLAIMED or update_type == FILTER_ALL:
                updates.append(self.update_author_claimed)
            if update_type == FILTER_OPEN_ACCESS or update_type == FILTER_ALL:
                updates.append(self.update_open_access)
            if update_type == FILTER_PEER_REVIEWED or update_type == FILTER_ALL:
                updates.append(self.update_peer_reviewed)
        elif document_type == HYPOTHESIS:
            pass
        elif document_type == NOTE:
            return
        else:
            if update_type == FILTER_ANSWERED or update_type == FILTER_ALL:
                updates.append(self.update_answered)
            if update_type == FILTER_PEER_REVIEWED or update_type == FILTER_ALL:
                updates.append(self.update_peer_reviewed)

        if update_type == FILTER_BOUNTY_OPEN or update_type == FILTER_ALL:
            updates.append(self.update_bounty_open)
        if update_type == FILTER_BOUNTY_CLOSED or update_type == FILTER_ALL:
            updates.append(self.update_bounty_closed)
        if update_type == FILTER_BOUNTY_EXPIRED or update_type == FILTER_ALL:
            updates.append(self.update_bounty_expired)
        if update_type == FILTER_HAS_BOUNTY or update_type == FILTER_ALL:
            updates.append(self.update_has_bounty)
        if update_type == SORT_BOUNTY_EXPIRATION_DATE or update_type == FILTER_ALL:
            updates.append(self.update_bounty_expiration_date)
        if update_type == SORT_BOUNTY_TOTAL_AMOUNT or update_type == FILTER_ALL:
            updates.append(self.update_bounty_total_amount)

        if update_type == SORT_DISCUSSED or update_type == FILTER_ALL:
            updates.append(self.update_discussed_today)
            updates.append(self.update_discussed_week)
            updates.append(self.update_discussed_month)
            updates.append(self.update_discussed_year)
            updates.append(self.update_discussed_all)
            updates.append(self.update_discussed_date)

        if update_type == SORT_UPVOTED or update_type == FILTER_ALL:
            updates.append(self.update_upvoted_today)
            updates.append(self.update_upvoted_week)
            updates.append(self.update_upvoted_month)
            updates.append(self.update_upvoted_year)
            updates.append(self.update_upvoted_all)
            updates.append(self.update_upvoted_date)

        for update in updates:
            try:
                update(unified_document, document)
            except Exception as e:
                log_error(e)
                # TODO: Delete print
                print(
                    "FILTERING UPDATE ERROR - ",
                    str(update),
                    e,
                    f" - {unified_document.id}",
                )

        self.save()

    def update_answered(self, unified_document, document):
        self.answered = document.threads.filter(is_accepted_answer=True).exists()

    def update_author_claimed(self, unified_document, document):
        self.author_claimed = document.related_claim_cases.filter(
            status="APPROVED"
        ).exists()

    def update_bounty_closed(self, unified_document, document):
        self.bounty_closed = unified_document.bounties.filter(
            status=Bounty.CLOSED
        ).exists()

    def update_bounty_expired(self, unified_document, document):
        self.bounty_expired = unified_document.bounties.filter(
            status=Bounty.EXPIRED
        ).exists()

    def update_bounty_open(self, unified_document, document):
        self.bounty_open = unified_document.bounties.filter(status=Bounty.OPEN).exists()

    def update_has_bounty(self, unified_document, document):
        self.has_bounty = unified_document.related_bounties.exists()

    def update_open_access(self, unified_document, document):
        self.open_access = document.oa_status != "closed"

    def update_peer_reviewed(self, unified_document, document):
        self.peer_reviewed = unified_document.reviews.exists()

    def update_bounty_expiration_date(self, unified_document, document):
        bounty = unified_document.bounties.last()
        if bounty:
            self.bounty_expiration_date = bounty.expiration_date

    def update_bounty_total_amount(self, unified_document, document):
        self.bounty_total_amount = unified_document.bounties.aggregate(
            total=Coalesce(Sum("amount", filter=Q(status=Bounty.OPEN)), 0)
        ).get("total", 0)

    def get_discussued(self, document, start_date, end_date):
        threads = document.threads
        thread_filter = Q(
            created_date__gte=start_date,
            created_date__lt=end_date,
            is_removed=False,
            created_by__isnull=False,
        )
        comment_filter = Q(
            comments__created_date__gte=start_date,
            comments__created_date__lt=end_date,
            comments__is_removed=False,
            comments__created_by__isnull=False,
        )
        reply_filter = Q(
            comments__replies__created_date__gte=start_date,
            comments__replies__created_date__lt=end_date,
            comments__replies__is_removed=False,
            comments__replies__created_by__isnull=False,
        )
        thread_ct = threads.filter(thread_filter).count()
        comment_ct = (
            threads.annotate(comments_ct=Count("comments", filter=comment_filter))
            .aggregate(ct=Coalesce(Sum("comments_ct"), 0))
            .get("ct", 0)
        )
        replies_ct = (
            threads.annotate(replies_ct=Count("comments__replies", filter=reply_filter))
            .aggregate(ct=Coalesce(Sum("replies_ct"), 0))
            .get("ct", 0)
        )
        return thread_ct + comment_ct + replies_ct

    def update_discussed_today(self, unified_document, document):
        # Same buffer as get_date_ranges_by_time_scope in researchhub_document/utils.py
        hours_buffer = 10
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(hours=(24 + hours_buffer))
        self.discussed_today = self.get_discussued(document, start_date, now)
        # self.discussed_today_date = now

    def update_discussed_week(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=7)
        self.discussed_week = self.get_discussued(document, start_date, now)
        # self.discussed_week_date = now

    def update_discussed_month(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=30)
        self.discussed_month = self.get_discussued(document, start_date, now)
        # self.discussed_month_date = now

    def update_discussed_year(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=365)
        self.discussed_year = self.get_discussued(document, start_date, now)
        # self.discussed_year_date = now

    def update_discussed_all(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = datetime(year=2018, month=12, day=31, hour=0, tzinfo=pytz.UTC)
        self.discussed_all = self.get_discussued(document, start_date, now)
        # self.discussed_all_date = now

    def update_discussed_date(self, unified_document, document):
        from discussion.models import Comment, Reply

        threads = document.threads
        comments = Comment.objects.filter(parent_id__in=threads.values("id"))
        replies = Reply.objects.filter(object_id__in=comments.values("id"))

        threads_latest_date = (
            threads.order_by("-created_date")
            .values_list("created_date", flat=True)
            .first()
        )
        comments_latest_date = (
            comments.order_by("-created_date")
            .values_list("created_date", flat=True)
            .first()
        )
        replies_latest_date = (
            replies.order_by("-created_date")
            .values_list("created_date", flat=True)
            .first()
        )

        dates = []
        if threads_latest_date:
            dates.append(threads_latest_date)
        if comments_latest_date:
            dates.append(comments_latest_date)
        if replies_latest_date:
            dates.append(replies_latest_date)
        latest_date = sorted(dates, reverse=True)
        if latest_date:
            self.discussed_date = latest_date[0]

    def get_upvotes(self, document, start_date, end_date):
        votes = document.votes.filter(
            created_date__gte=start_date, created_date__lt=end_date
        )
        annotated_votes = votes.aggregate(
            upvote_ct=Count("id", filter=Q(vote_type=1)),
            downvote_ct=Count("id", filter=Q(vote_type=2)),
        )
        score = annotated_votes.get("upvote_ct", 0) - annotated_votes.get(
            "downvote_ct", 0
        )
        return score

    def update_upvoted_today(self, unified_document, document):
        # Same buffer as get_date_ranges_by_time_scope in researchhub_document/utils.py
        hours_buffer = 10
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(hours=(24 + hours_buffer))
        self.upvoted_today = self.get_upvotes(document, start_date, now)
        # self.upvoted_today_date = now

    def update_upvoted_week(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=7)
        self.upvoted_week = self.get_upvotes(document, start_date, now)
        # self.upvoted_week_date = now

    def update_upvoted_month(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=30)
        self.upvoted_month = self.get_upvotes(document, start_date, now)
        # self.upvoted_month_date = now

    def update_upvoted_year(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=365)
        self.upvoted_year = self.get_upvotes(document, start_date, now)
        # self.upvoted_year_date = now

    def update_upvoted_all(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = datetime(year=2018, month=12, day=31, hour=0, tzinfo=pytz.UTC)
        self.upvoted_all = self.get_upvotes(document, start_date, now)
        # self.upvoted_all_date = now

    def update_upvoted_date(self, unified_document, document):
        latest_vote_date = (
            document.votes.order_by("-created_date")
            .values_list("created_date", flat=True)
            .first()
        )
        if latest_vote_date:
            self.upvoted_date = latest_vote_date


class ResearchhubUnifiedDocument(DefaultModel, HotScoreMixin):
    is_public = models.BooleanField(
        default=True, help_text="Unified document is public"
    )
    is_removed = models.BooleanField(
        default=False, db_index=True, help_text="Unified Document is removed (deleted)"
    )
    document_type = models.CharField(
        choices=DOCUMENT_TYPES,
        default=PAPER,
        max_length=32,
        null=False,
        help_text="Papers are imported from external src. Posts are in-house",
    )
    published_date = models.DateTimeField(auto_now_add=True, null=True)
    score = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Another feed ranking score.",
    )
    hot_score = models.IntegerField(
        default=0,
        help_text="Feed ranking score.",
    )
    hot_score_v2 = models.IntegerField(
        default=0, help_text="Feed ranking score.", db_index=True
    )
    permissions = GenericRelation(
        Permission,
        related_name="unified_document",
        related_query_name="uni_doc_source",
    )
    bounties = GenericRelation(
        "reputation.Bounty",
        content_type_field="item_content_type",
        object_id_field="item_object_id",
    )
    hubs = models.ManyToManyField(Hub, related_name="related_documents", blank=True)
    document_filter = models.OneToOneField(
        DocumentFilter, on_delete=models.CASCADE, related_name="unified_document"
    )

    class Meta:
        indexes = (
            models.Index(
                fields=("created_date",),
                name="uni_doc_created_date_idx",
            ),
        )

    def update_filter(self, filter_type):
        self.document_filter.update_filter(filter_type)

    def update_filters(self, filter_types):
        for filter_type in filter_types:
            self.update_filter(filter_type)

    @property
    def authors(self):
        # This property needs to return a queryset
        # which is why we are filtering by authors

        if hasattr(self, "paper"):
            return self.paper.authors.all()

        if hasattr(self, "hypothesis"):
            author = Author.objects.filter(user=self.hypothesis.created_by)
            return author

        posts = self.posts
        if posts.exists():
            post = posts.last()
            author = Author.objects.filter(user=post.created_by)
            return author
        return Author.objects.none()

    def get_url(self):
        if self.document_type == PAPER:
            doc_url = "paper"
        elif self.document_type == DISCUSSION:
            doc_url = "post"
        elif self.document_type == HYPOTHESIS:
            doc_url = "hypothesis"
        else:
            # TODO: fill this with proper url for other doc types
            return None

        doc = self.get_document()

        return "{}/{}/{}/{}".format(BASE_FRONTEND_URL, doc_url, doc.id, doc.slug)

    def get_hub_names(self):
        return ",".join(self.hubs.values_list("name", flat=True))

    def get_document(self):
        if self.document_type == PAPER:
            return self.paper
        elif self.document_type == DISCUSSION:
            return self.posts.first()
        elif self.document_type == HYPOTHESIS:
            return self.hypothesis
        elif self.document_type == NOTE:
            return self.note
        elif self.document_type == QUESTION:
            return self.posts.first()
        else:
            raise Exception(f"Unrecognized document_type: {self.document_type}")

    @property
    def created_by(self):
        if self.document_type == PAPER:
            return self.paper.uploaded_by
        else:
            first_post = self.posts.first()
            if first_post is not None:
                return first_post.created_by
            return None

    def get_review_details(self):
        details = {"avg": 0, "count": 0}
        reviews = self.reviews.values_list("score", flat=True)
        if reviews:
            details["avg"] = round(mean(reviews), 1)
            details["count"] = reviews.count()
        return details

    def save(self, **kwargs):
        if not hasattr(self, "document_filter"):
            self.document_filter = DocumentFilter.objects.create()
        super().save(**kwargs)

        # Update the Elastic Search index for post records.
        try:
            for post in self.posts.all():
                update_elastic_registry.apply_async(post)
        except:
            pass
