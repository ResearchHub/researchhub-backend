import datetime

from django.db import models
from django.contrib.postgres.fields import JSONField
from django_elasticsearch_dsl_drf.wrappers import dict_to_obj

from hub.models import Hub
from user.models import Author, User
from summary.models import Summary
from utils.voting import calculate_score


class LowerCharField(models.CharField):
    """
    CharField but where values are converted to lowercase.
    Useful for case-insensitive strings like DOIs.

    FIXME: could not use for Paper.doi due to:
    django_elasticsearch_dsl.exceptions.ModelFieldNotMappedError: Cannot convert model field doi to an Elasticsearch field! # noqa E501
    """
    def __init__(self, *args, **kwargs):
        super(LowerCharField, self).__init__(*args, **kwargs)

    def get_prep_value(self, value):
        return str(value).lower()


class Paper(models.Model):
    title = models.CharField(max_length=1024)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    uploaded_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    paper_publish_date = models.DateField(null=True)
    authors = models.ManyToManyField(
        Author,
        related_name='authored_papers',
        blank=True
    )
    moderators = models.ManyToManyField(
        User,
        related_name='moderated_papers',
        blank=True
    )
    doi = models.CharField(max_length=255, default='', blank=True)
    hubs = models.ManyToManyField(
        Hub,
        related_name='papers',
        blank=True
    )
    url = models.URLField(default='', blank=True)
    summary = models.ForeignKey(
        Summary,
        blank=True,
        null=True,
        related_name='papers',
        on_delete='SET NULL'
    )
    file = models.FileField(upload_to='uploads/papers/%Y/%m/%d')
    tagline = models.TextField(
        null=True,
        blank=True
    )
    publication_type = models.CharField(max_length=255, default='', blank=True)
    csl_item = JSONField(
        default=dict,
        help_text='bibliographic metadata as a single '
                  'Citation Styles Language JSON item.'
    )

    @classmethod
    def create_from_csl_item(cls, csl_item):
        paper = cls(title=csl_item['title'])
        try:
            date_parts = csl_item['issued']['date-parts'][0]
            if date_parts:
                while len(date_parts) < 3:
                    date_parts.append(1)
                paper.paper_publish_date = datetime.date(*map(int, date_parts))
        except KeyError:
            pass
        if 'DOI' in csl_item:
            paper.doi = csl_item['DOI'].lower()
        return paper

    def __str__(self):
        return '{} - {}'.format(self.title, self.uploaded_by)

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
        return self.get_score()

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
        return self.threads.count()

    def get_score(self):
        if self.votes:
            return calculate_score(self, Vote.UPVOTE, Vote.DOWNVOTE)
        return 0

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
        User,
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
        User,
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
