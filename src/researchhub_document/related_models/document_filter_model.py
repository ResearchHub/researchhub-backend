from datetime import datetime, timedelta

import pytz
from django.db import models
from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce

from reputation.models import Bounty
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.constants.document_type import (
    FILTER_ALL,
    FILTER_ANSWERED,
    FILTER_AUTHOR_CLAIMED,
    FILTER_BOUNTY_CLOSED,
    FILTER_BOUNTY_EXPIRED,
    FILTER_BOUNTY_OPEN,
    FILTER_EXCLUDED_FROM_FEED,
    FILTER_HAS_BOUNTY,
    FILTER_INCLUDED_IN_FEED,
    FILTER_OPEN_ACCESS,
    FILTER_PEER_REVIEWED,
    HYPOTHESIS,
    NOTE,
    PAPER,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
    SORT_DISCUSSED,
    SORT_UPVOTED,
)
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
    is_excluded = models.BooleanField(default=False, db_index=True)

    # Sorting Fields
    bounty_expiration_date = models.DateTimeField(null=True)
    bounty_total_amount = models.DecimalField(
        decimal_places=10, max_digits=19, null=True, db_index=True
    )

    discussed_today = models.IntegerField(default=0, db_index=True)
    discussed_week = models.IntegerField(default=0, db_index=True)
    discussed_month = models.IntegerField(default=0, db_index=True)
    discussed_year = models.IntegerField(default=0, db_index=True)
    discussed_all = models.IntegerField(default=0, db_index=True)
    discussed_date = models.DateTimeField(auto_now_add=True)

    upvoted_today = models.IntegerField(default=0, db_index=True)
    upvoted_week = models.IntegerField(default=0, db_index=True)
    upvoted_month = models.IntegerField(default=0, db_index=True)
    upvoted_year = models.IntegerField(default=0, db_index=True)
    upvoted_all = models.IntegerField(default=0, db_index=True)
    upvoted_date = models.DateTimeField(auto_now_add=True)

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

        if update_type == FILTER_INCLUDED_IN_FEED:
            updates.append(self.update_included)
        elif update_type == FILTER_EXCLUDED_FROM_FEED:
            updates.append(self.update_excluded)

        for update in updates:
            try:
                update(unified_document, document)
            except Exception as e:
                log_error(e)

        self.save()

    def update_answered(self, unified_document, document):
        self.answered = document.threads.filter(is_accepted_answer=True).exists()

    def update_excluded(self, unified_document, document):
        self.is_excluded = True

    def update_included(self, unified_document, document):
        self.is_excluded = False

    def update_author_claimed(self, unified_document, document):
        self.author_claimed = document.related_claim_cases.filter(
            status="APPROVED"
        ).exists()

    def update_bounty_closed(self, unified_document, document):
        self.bounty_closed = unified_document.related_bounties.filter(
            status=Bounty.CLOSED
        ).exists()

    def update_bounty_expired(self, unified_document, document):
        self.bounty_expired = unified_document.related_bounties.filter(
            status=Bounty.EXPIRED
        ).exists()

    def update_bounty_open(self, unified_document, document):
        self.bounty_open = unified_document.related_bounties.filter(
            status=Bounty.OPEN
        ).exists()

    def update_has_bounty(self, unified_document, document):
        self.has_bounty = unified_document.related_bounties.exists()

    def update_open_access(self, unified_document, document):
        is_open_access = document.oa_status and document.oa_status != "closed"
        if is_open_access:
            self.open_access = True
        else:
            self.open_access = False

    def update_peer_reviewed(self, unified_document, document):
        self.peer_reviewed = unified_document.reviews.exists()

    def update_bounty_expiration_date(self, unified_document, document):
        bounty = unified_document.related_bounties.filter(status=Bounty.OPEN).last()
        if bounty:
            self.bounty_expiration_date = bounty.expiration_date
        else:
            self.bounty_expiration_date = None

    def update_bounty_total_amount(self, unified_document, document):
        self.bounty_total_amount = unified_document.related_bounties.aggregate(
            total=Coalesce(
                Sum("amount", filter=Q(status=Bounty.OPEN)),
                0,
                output_field=DecimalField(),
            )
        ).get("total", 0)

    def get_discussued(self, document, start_date, end_date):
        threads = document.rh_threads
        qs = threads.filter(
            rh_comments__created_date__gte=start_date,
            rh_comments__created_date__lt=end_date,
        ).filter(
            (Q(rh_comments__is_removed=False) & Q(rh_comments__parent__isnull=True))
            | (
                Q(rh_comments__parent__is_removed=False)
                & Q(rh_comments__parent__isnull=False)
            )
        )
        return qs.count()

    def update_discussed_today(self, unified_document, document):
        # Same buffer as get_date_ranges_by_time_scope in researchhub_document/utils.py
        hours_buffer = 10
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(hours=(24 + hours_buffer))
        self.discussed_today = self.get_discussued(document, start_date, now)

    def update_discussed_week(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=7)
        self.discussed_week = self.get_discussued(document, start_date, now)

    def update_discussed_month(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=30)
        self.discussed_month = self.get_discussued(document, start_date, now)

    def update_discussed_year(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=365)
        self.discussed_year = self.get_discussued(document, start_date, now)

    def update_discussed_all(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = datetime(year=2018, month=12, day=31, hour=0, tzinfo=pytz.UTC)
        self.discussed_all = self.get_discussued(document, start_date, now)

    def update_discussed_date(self, unified_document, document):
        thread_ids = document.rh_threads.values_list("id")
        comments_latest_date = (
            RhCommentModel.objects.filter(thread__in=thread_ids)
            .order_by("-created_date")
            .values_list("created_date", flat=True)
            .first()
        )

        if not comments_latest_date:
            self.discussed_date = unified_document.created_date
        else:
            self.discussed_date = comments_latest_date
        self.discussed_date_ts = self.discussed_date.timestamp()

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

    def update_upvoted_week(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=7)
        self.upvoted_week = self.get_upvotes(document, start_date, now)

    def update_upvoted_month(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=30)
        self.upvoted_month = self.get_upvotes(document, start_date, now)

    def update_upvoted_year(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = now - timedelta(days=365)
        self.upvoted_year = self.get_upvotes(document, start_date, now)

    def update_upvoted_all(self, unified_document, document):
        now = datetime.now(pytz.UTC)
        start_date = datetime(year=2018, month=12, day=31, hour=0, tzinfo=pytz.UTC)
        self.upvoted_all = self.get_upvotes(document, start_date, now)

    def update_upvoted_date(self, unified_document, document):
        latest_vote_date = (
            document.votes.order_by("-created_date")
            .values_list("created_date", flat=True)
            .first()
        )
        if latest_vote_date:
            self.upvoted_date = latest_vote_date
