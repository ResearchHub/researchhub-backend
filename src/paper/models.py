import datetime

from django.db import models
from django.db.models import Count, Q
from django.contrib.postgres.fields import JSONField
from django_elasticsearch_dsl_drf.wrappers import dict_to_obj

from summary.models import Summary

HELP_TEXT_IS_PUBLIC = (
    'Hides the paper from the public.'
)
HELP_TEXT_IS_REMOVED = (
    'Hides the paper because it is not allowed.'
)


class Paper(models.Model):
    title = models.CharField(max_length=1024)  # User generated title
    uploaded_by = models.ForeignKey(
        'user.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    uploaded_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    paper_publish_date = models.DateField(null=True)
    authors = models.ManyToManyField(
        'user.Author',
        related_name='authored_papers',
        blank=True
    )
    # Moderators are obsolete, in favor of super mods on the user
    moderators = models.ManyToManyField(
        'user.User',
        related_name='moderated_papers',
        blank=True
    )
    references = models.ManyToManyField(
        'self',
        related_name='referenced_by',
        blank=True
    )
    paper_title = models.CharField(  # Official paper title
        max_length=1024,
        default=None,
        null=True,
        blank=True
    )
    doi = models.CharField(max_length=255, default=None, null=True, blank=True)
    hubs = models.ManyToManyField(
        'hub.Hub',
        related_name='papers',
        blank=True
    )
    # currently this is the url entered by users during upload (seed URL)
    url = models.URLField(
        max_length=512,
        default=None,
        null=True,
        blank=True
    )
    summary = models.ForeignKey(
        Summary,
        blank=True,
        null=True,
        related_name='papers',
        on_delete=models.SET_NULL
    )
    file = models.FileField(
        max_length=512,
        upload_to='uploads/papers/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    pdf_file_license = models.TextField(default=None, null=True, blank=True)
    pdf_url = models.URLField(
        max_length=512,
        default=None,
        null=True,
        blank=True
    )
    pdf_url_for_landing_page = models.URLField(
        max_length=512,
        default=None,
        null=True,
        blank=True
    )
    tagline = models.TextField(
        default=None,
        null=True,
        blank=True
    )
    publication_type = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    csl_item = JSONField(
        default=None,
        null=True,
        blank=True,
        help_text='bibliographic metadata as a single '
                  'Citation Styles Language JSON item.'
    )
    pdf_location = JSONField(
        default=None,
        null=True,
        blank=True,
        help_text='information on PDF availability '
                  'in the Unpaywall OA Location data format.'
    )
    retrieved_from_external_source = models.BooleanField(default=False)
    is_public = models.BooleanField(
        default=True,
        help_text=HELP_TEXT_IS_PUBLIC
    )
    is_removed = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_IS_REMOVED
    )

    class Meta:
        ordering = ['-paper_publish_date']

    @property
    def is_hidden(self):
        return (not self.is_public) or self.is_removed

    @property
    def owners(self):
        mods = list(self.moderators.all())
        authors = list(self.authors.all())
        return mods + authors

    @property
    def users_to_notify(self):
        users = list(self.moderators.all())
        paper_authors = self.authors.all()
        for author in paper_authors:
            if (
                author.user
                and author.user.emailrecipient.paper_subscription.threads
                and not author.user.emailrecipient.paper_subscription.none
            ):
                users.append(author.user)
        return users

    @property
    def children(self):
        return self.threads.all()

    @classmethod
    def create_from_csl_item(
        cls,
        csl_item,
        doi=None,
        externally_sourced=False,
        is_public=None
    ):
        """
        Create a paper object from a CSL_Item.
        This may be useful if we want to auto-populate the paper
        database at some point.
        """
        from manubot.cite.csl_item import CSL_Item

        if not isinstance(csl_item, CSL_Item):
            csl_item = CSL_Item(csl_item)

        paper = cls(title=csl_item['title'], paper_title=csl_item['title'])

        date = csl_item.get_date("issued", fill=True)
        if date:
            paper.paper_publish_date = datetime.date.fromisoformat(date)

        if doi is not None:
            paper.doi = doi
        if 'DOI' in csl_item:
            paper.doi = csl_item['DOI'].lower()

        paper.csl_item = csl_item

        paper.retrieved_from_external_source = externally_sourced

        paper.is_public = True
        if externally_sourced is True:
            paper.is_public = False

        paper.save()
        return paper

    def __str__(self):
        if self.title and self.uploaded_by:
            return '{} - {}'.format(self.title, self.uploaded_by)
        elif self.title:
            return self.title
        else:
            return 'titleless paper'

    @property
    def authors_indexing(self):
        '''Authors for Elasticsearch indexing.'''
        return [self.get_full_name(author) for author in self.authors.all()]

    @property
    def discussion_count_indexing(self):
        '''Number of discussions.'''
        return self.get_discussion_count()

    @property
    def hubs_indexing(self):
        return [hub.name for hub in self.hubs.all()]

    @property
    def score_indexing(self):
        '''Score for Elasticsearch indexing.'''
        return self.calculate_score()

    @property
    def summary_indexing(self):
        if self.summary:
            return self.summary.summary_plain_text
        return ''

    @property
    def votes_indexing(self):
        all_votes = self.votes.all()
        if len(all_votes) > 0:
            return [self.get_vote_for_index(vote) for vote in all_votes]
        return {}

    def get_full_name(self, author_or_user):
        return f'{author_or_user.first_name} {author_or_user.last_name}'

    def get_discussion_count(self):
        if hasattr(self, 'discussion_count'):
            return self.discussion_count
        else:
            thread_count = self.threads.aggregate(
                discussion_count=Count(1, filter=Q(is_removed=False))
            )['discussion_count']
            comment_count = self.threads.aggregate(
                discussion_count=Count(
                    'comments',
                    filter=Q(comments__is_removed=False)
                )
            )['discussion_count']
            reply_count = self.threads.aggregate(
                discussion_count=Count(
                    'comments__replies',
                    filter=Q(comments__replies__is_removed=False)
                )
            )['discussion_count']
            return thread_count + comment_count + reply_count

    def calculate_score(self):
        if hasattr(self, 'score'):
            return self.score
        else:
            upvotes = self.votes.filter(vote_type=Vote.UPVOTE).count()
            downvotes = self.votes.filter(vote_type=Vote.DOWNVOTE).count()
            score = upvotes - downvotes
            return score

    def get_vote_for_index(self, vote):
        wrapper = dict_to_obj({
            'vote_type': vote.vote_type,
            'updated_date': vote.updated_date,
        })

        return wrapper

    def update_summary(self, summary):
        self.summary = summary
        self.save()


class Vote(models.Model):
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name='votes',
        related_query_name='vote'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='paper_votes',
        related_query_name='paper_vote'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['paper', 'created_by'],
                name='unique_paper_vote'
            )
        ]

    def __str__(self):
        return '{} - {}'.format(self.created_by, self.vote_type)


class Flag(models.Model):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name='flags',
        related_query_name='flag'
    )
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='paper_flags',
        related_query_name='paper_flag'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['paper', 'created_by'],
                name='unique_paper_flag'
            )
        ]
