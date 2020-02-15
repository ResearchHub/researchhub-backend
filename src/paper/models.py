import datetime

from django.db import models
from django.contrib.postgres.fields import JSONField
from django_elasticsearch_dsl_drf.wrappers import dict_to_obj

from summary.models import Summary
from utils.voting import calculate_score


class Paper(models.Model):
    title = models.CharField(max_length=1024)
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
    paper_title = models.CharField(max_length=1024, default='', blank=True)
    doi = models.CharField(max_length=255, default='', blank=True)
    hubs = models.ManyToManyField(
        'hub.Hub',
        related_name='papers',
        blank=True
    )
    # currently this is the url entered by users during upload (seed URL)
    url = models.URLField(default='', blank=True, max_length=500)
    summary = models.ForeignKey(
        Summary,
        blank=True,
        null=True,
        related_name='papers',
        on_delete=models.SET_NULL
    )
    file = models.FileField(upload_to='uploads/papers/%Y/%m/%d')
    pdf_file_license = models.TextField(default='', blank=True)
    pdf_url = models.URLField(default='', blank=True, max_length=500)
    pdf_url_for_landing_page = models.URLField(default='', blank=True, max_length=500)
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
    pdf_location = JSONField(
        default=dict,
        help_text='information on PDF availability '
                  'in the Unpaywall OA Location data format.'
    )
    class Meta:
        ordering = ['-paper_publish_date']

    @property
    def owners(self):
        mods = list(self.moderators.all())
        authors = list(self.authors.all())
        return mods + authors

    @property
    def children(self):
        return self.threads.all()

    @classmethod
    def create_from_csl_item(cls, csl_item):
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
        if 'DOI' in csl_item:
            paper.doi = csl_item['DOI'].lower()
        paper.csl_item = csl_item
        paper.save()
        return paper

    def __str__(self):
        if self.title and self.uploaded_by:
            return '{} - {}'.format(self.title, self.uploaded_by)
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
            return self.threads.count()

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
