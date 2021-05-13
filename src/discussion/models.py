from django.db.models import (
    Count,
    Q,
    F
)
from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation
)
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.core.cache import cache
from django.db import models

from paper.utils import get_cache_key
from purchase.models import Purchase
from researchhub.lib import CREATED_LOCATIONS

HELP_TEXT_WAS_EDITED = (
    'True if the comment text was edited after first being created.'
)
HELP_TEXT_IS_PUBLIC = (
    'Hides the comment from the public.'
)
HELP_TEXT_IS_REMOVED = (
    'Hides the comment because it is not allowed.'
)


class Vote(models.Model):
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    distributions = GenericRelation(
        'reputation.Distribution',
        object_id_field='proof_item_object_id',
        content_type_field='proof_item_content_type'
    )
    created_by = models.ForeignKey('user.User', on_delete=models.CASCADE, related_name='discussion_votes')
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'created_by'],
                name='unique_vote'
            )
        ]

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.vote_type)

    @property
    def paper(self):
        return self.item.paper


class Flag(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    created_by = models.ForeignKey('user.User', on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'created_by'],
                name='unique_flag'
            )
        ]


class Endorsement(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    created_by = models.ForeignKey('user.User', on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                name='unique_endorsement'
            )
        ]


class BaseComment(models.Model):
    CREATED_LOCATION_PROGRESS = CREATED_LOCATIONS['PROGRESS']
    CREATED_LOCATION_CHOICES = [
        (CREATED_LOCATION_PROGRESS, 'Progress')
    ]

    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_date = models.DateTimeField(auto_now=True)
    created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    was_edited = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_WAS_EDITED
    )
    is_public = models.BooleanField(
        default=True,
        help_text=HELP_TEXT_IS_PUBLIC
    )
    is_removed = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_IS_REMOVED
    )
    ip_address = models.GenericIPAddressField(
        unpack_ipv4=True,
        blank=True,
        null=True
    )
    text = JSONField(blank=True, null=True)
    external_metadata = JSONField(null=True)
    votes = GenericRelation(
        Vote,
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='discussion'
    )
    flags = GenericRelation(Flag)
    endorsement = GenericRelation(Endorsement)
    plain_text = models.TextField(default='', blank=True)
    source = models.CharField(default='researchhub', max_length=32, null=True)
    purchases = GenericRelation(
        Purchase,
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='discussion'
    )

    class Meta:
        abstract = True

    # TODO make this a mixin Actionable or Notifiable
    @property
    def owners(self):
        if self.created_by:
            return [self.created_by]
        else:
            return []

    # TODO make this a mixin Actionable or Notifiable
    @property
    def users_to_notify(self):
        parent_owners = self.parent.owners
        return parent_owners

    @property
    def created_by_author_profile_indexing(self):
        if self.created_by:
            author = self.created_by.author_profile
            if author:
                return author
        return None

    @property
    def children(self):
        return BaseComment.objects.none()

    @property
    def score_indexing(self):
        return self.calculate_score()

    def calculate_score(self, ignore_self_vote=False):
        if hasattr(self, 'score'):
            return self.score
        else:
            qs = self.votes.filter(
                created_by__is_suspended=False,
                created_by__probable_spammer=False
            )

            if ignore_self_vote:
                qs = qs.exclude(created_by=F('discussion__created_by'))

            score = qs.aggregate(
                score=Count(
                    'id', filter=Q(vote_type=Vote.UPVOTE)
                ) - Count(
                    'id', filter=Q(vote_type=Vote.DOWNVOTE)
                )
            ).get('score', 0)
            return score

    def update_discussion_count(self):
        paper = self.paper
        if paper:
            new_dis_count = paper.get_discussion_count()
            paper.calculate_hot_score()

            paper.discussion_count = new_dis_count
            paper.save(update_fields=['discussion_count'])

            cache_key = get_cache_key('paper', paper.id)
            cache.delete(cache_key)

            for h in paper.hubs.all():
                h.discussion_count = h.get_discussion_count()
                h.save(update_fields=['discussion_count'])

            return new_dis_count
        return 0

    def remove_nested(self):
        if self.is_removed is False:
            self.is_removed = True
            self.save(update_fields=['is_removed'])
        if len(self.children) > 0:
            for c in self.children:
                c.remove_nested()

    def get_promoted_score(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID,
        )
        if purchases.exists():
            boost_score = sum(
                map(int, purchases.values_list('amount', flat=True))
            )
            return boost_score
        return False


class Thread(BaseComment):
    RESEARCHHUB = 'researchhub'
    INLINE_ABSTRACT = 'inline_abstract'
    INLINE_PAPER_BODY = 'inline_paper_body'
    THREAD_SOURCE_CHOICES = [
        (RESEARCHHUB, 'researchhub'),
        (INLINE_ABSTRACT, 'Inline Abstract'),
        (INLINE_PAPER_BODY, 'Inline Paper Body')
    ]
    source = models.CharField(
        default=RESEARCHHUB,
        choices=THREAD_SOURCE_CHOICES,
        max_length=32
    )
    block_key = models.CharField(max_length=255, null=True, blank=True)
    context_title = models.TextField(
        blank=True,
        null=True,
        help_text="For inline-comments, indicates what's highlighted"
    )
    entity_key = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )
    paper = models.ForeignKey(
        'paper.Paper',
        on_delete=models.SET_NULL,
        related_name='threads',
        blank=True,
        null=True
    )
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='threads'
    )

    def __str__(self):
        return '%s: %s' % (self.created_by, self.title)

    @property
    def parent(self):
        return self.paper

    @property
    def children(self):
        return self.comments.filter(is_removed=False)

    @property
    def comment_count_indexing(self):
        return len(self.comments.filter(is_removed=False))

    @property
    def paper_indexing(self):
        if self.paper is not None:
            return self.paper.id

    @property
    def paper_title_indexing(self):
        if self.paper is not None:
            return self.paper.title

    @property
    def owners(self):
        if (
            self.created_by
            and self.created_by.emailrecipient.thread_subscription
            and not self.created_by.emailrecipient.thread_subscription.none
        ):
            return [self.created_by]
        else:
            return []

    @property
    def users_to_notify(self):
        users = list(self.parent.moderators.all())
        paper_authors = self.parent.authors.all()
        for author in paper_authors:
            if (
                author.user
                and author.user.emailrecipient.paper_subscription.threads
                and not author.user.emailrecipient.paper_subscription.none
            ):
                users.append(author.user)
        return users


class Reply(BaseComment):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    object_id = models.PositiveIntegerField()
    parent = GenericForeignKey('content_type', 'object_id')
    replies = GenericRelation('Reply')
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='replies'
    )

    @property
    def paper(self):
        comment = self.get_comment_of_reply()
        paper = comment.paper
        return paper

    @property
    def thread(self):
        comment = self.get_comment_of_reply()
        thread = comment.parent
        return thread

    @property
    def children(self):
        return self.replies.filter(is_removed=False)

    def get_comment_of_reply(self):
        obj = self
        while isinstance(obj, Reply):
            obj = obj.parent

        if isinstance(obj, Comment):
            return obj
        return None

    @property
    def owners(self):
        return [self.created_by]

    @property
    def users_to_notify(self):
        # TODO: No siblings for now. Do we need this?
        # sibling_comment_users = []
        # for c in self.parent.children.prefetch_related(
        #     'created_by',
        #     'created_by__emailrecipient',
        #     'created_by__emailrecipient__thread_subscription',
        #     'created_by__emailrecipient__comment_subscription'
        # ):
        #     if (
        #         c != self
        #         and c.created_by not in sibling_comment_users
        #         and c.created_by.emailrecipient.thread_subscription
        #         and c.created_by.emailrecipient.thread_subscription.replies
        #         and c.created_by.emailrecipient.comment_subscription
        #         and c.created_by.emailrecipient.comment_subscription.replies
        #     ):
        #         sibling_comment_users.append(c.created_by)
        # return parent_owners + sibling_comment_users
        users = []
        p = self.parent
        if isinstance(p, Reply):
            if (
                p.created_by
                and p.created_by.emailrecipient.reply_subscription.replies
                and not p.created_by.emailrecipient.reply_subscription.none
            ):
                users.append(p.created_by)
        else:
            if (
                p.created_by
                and p.created_by.emailrecipient.comment_subscription.replies
                and not p.created_by.emailrecipient.comment_subscription.none
            ):
                users.append(p.created_by)
        return users


class Comment(BaseComment):
    parent = models.ForeignKey(
        Thread,
        on_delete=models.SET_NULL,
        related_name='comments',
        blank=True,
        null=True
    )
    replies = GenericRelation(Reply)
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='comments'
    )

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.plain_text)

    @property
    def paper(self):
        thread = self.parent
        if thread:
            paper = thread.paper
            return paper

    @property
    def thread(self):
        thread = self.parent
        return thread

    @property
    def children(self):
        return self.replies.filter(is_removed=False)

    @property
    def owners(self):
        return [self.created_by]

    @property
    def users_to_notify(self):
        users = []
        p = self.parent
        if (
            p.created_by
            and p.created_by.emailrecipient.thread_subscription.comments
            and not p.created_by.emailrecipient.thread_subscription.none
        ):
            users.append(p.created_by)
        return users
        # TODO: No siblings for now. Do we need this?
        # sibling_comment_users = []
        # for c in self.parent.children.prefetch_related(
        #     'created_by',
        #     'created_by__emailrecipient',
        #     'created_by__emailrecipient__thread_subscription'
        # ):
        #    if (
        #         c != self
        #         and c.created_by not in sibling_comment_users
        #         and c.created_by.emailrecipient.thread_subscription
        #         and c.created_by.emailrecipient.thread_subscription.comments
        #     ):
        #         sibling_comment_users.append(c.created_by)
        # return parent_owners + sibling_comment_users
