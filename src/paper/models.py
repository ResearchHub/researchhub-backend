from django.contrib.postgres.fields import JSONField
from django.db import models
from django.db.models import Count, Q
from django_elasticsearch_dsl_drf.wrappers import dict_to_obj

from utils.semantic_scholar import SemanticScholar
from utils.crossref import Crossref
from manubot.cite.doi import get_doi_csl_item

from paper.utils import MANUBOT_PAPER_TYPES
from .tasks import (
    celery_extract_figures,
    celery_extract_pdf_preview,
    celery_extract_meta_data
)
from researchhub.settings import TESTING
from summary.models import Summary
from hub.models import Hub

HELP_TEXT_IS_PUBLIC = (
    'Hides the paper from the public.'
)
HELP_TEXT_IS_REMOVED = (
    'Hides the paper because it is not allowed.'
)


class Paper(models.Model):
    uploaded_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    is_public = models.BooleanField(
        default=True,
        help_text=HELP_TEXT_IS_PUBLIC
    )
    is_removed = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_IS_REMOVED
    )
    score = models.IntegerField(default=0)
    discussion_count = models.IntegerField(default=0)

    # Moderators are obsolete, in favor of super mods on the user
    moderators = models.ManyToManyField(
        'user.User',
        related_name='moderated_papers',
        blank=True
    )
    authors = models.ManyToManyField(
        'user.Author',
        related_name='authored_papers',
        blank=True
    )
    hubs = models.ManyToManyField(
        'hub.Hub',
        related_name='papers',
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
    retrieved_from_external_source = models.BooleanField(default=False)
    external_source = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )

    # User generated
    title = models.CharField(max_length=1024)  # User generated title
    tagline = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    uploaded_by = models.ForeignKey(
        'user.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )

    # Metadata
    doi = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True,
        unique=True
    )
    paper_title = models.CharField(  # Official paper title
        max_length=1024,
        default=None,
        null=True,
        blank=True
    )
    paper_publish_date = models.DateField(null=True)
    raw_authors = JSONField(blank=True, null=True)
    abstract = models.TextField(
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
    references = models.ManyToManyField(
        'self',
        symmetrical=False,
        related_name='referenced_by',
        blank=True
    )
    # Can be the url entered by users during upload (seed URL)
    url = models.URLField(
        max_length=1024,
        default=None,
        null=True,
        blank=True
    )
    pdf_url = models.URLField(
        max_length=1024,
        default=None,
        null=True,
        blank=True
    )
    pdf_license = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    pdf_license_url = models.URLField(
        max_length=1024,
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
    oa_pdf_location = JSONField(
        default=None,
        null=True,
        blank=True,
        help_text='PDF availability in Unpaywall OA Location format.'
    )

    class Meta:
        ordering = ['-paper_publish_date']

    def __str__(self):
        if self.title and self.uploaded_by:
            return '{} - {}'.format(self.title, self.uploaded_by)
        elif self.title:
            return self.title
        else:
            return 'titleless paper'

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
    def create_manubot_paper(cls, doi):
        csl_item = get_doi_csl_item(doi)
        return Paper.create_from_csl_item(
            csl_item,
            doi=doi,
            externally_sourced=True,
            is_public=False
        )

    @classmethod
    def create_crossref_paper(cls, doi):
        return Crossref(doi=doi).create_paper()

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

        if csl_item['type'] not in MANUBOT_PAPER_TYPES:
            return None

        is_public = True
        external_source = None
        if externally_sourced is True:
            is_public = False
            external_source = 'manubot'

        if 'DOI' in csl_item:
            doi = csl_item['DOI'].lower()

        paper_publish_date = csl_item.get_date('issued', fill=True)

        paper = cls(
            doi=doi,
            is_public=is_public,
            title=csl_item.get('title', None),
            paper_title=csl_item.get('title', None),
            url=csl_item.get('URL', None),
            csl_item=csl_item,
            external_source=external_source,
            retrieved_from_external_source=externally_sourced,
            paper_publish_date=paper_publish_date,
            tagline=csl_item.get('abstract', None)
        )
        paper.save()
        return paper

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

    def extract_figures(self, use_celery=True):
        if TESTING:
            return

        if not TESTING and use_celery:
            celery_extract_figures.apply_async(
                (self.id,),
                priority=3,
                countdown=10,
            )
        else:
            celery_extract_figures(self.id)

    def extract_pdf_preview(self, use_celery=True):
        if TESTING:
            return

        if not TESTING and use_celery:
            celery_extract_pdf_preview.apply_async(
                (self.id,),
                priority=3,
                countdown=10,
            )
        else:
            celery_extract_pdf_preview(self.id)

    def extract_meta_data(
        self,
        title=None,
        check_title=False,
        use_celery=True
    ):
        if TESTING:
            return

        if title is None and self.paper_title:
            title = self.paper_title
        elif title is None and self.title:
            title = self.title
        elif title is None:
            return

        if not TESTING and use_celery:
            celery_extract_meta_data.apply_async(
                (self.id, title, check_title),
                priority=1,
                countdown=10,
            )
        else:
            celery_extract_meta_data(self.id, title, check_title)

    def calculate_score(self):
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

    def add_references(self):
        if self.doi:
            semantic_paper = SemanticScholar(self.doi)
            references = semantic_paper.references
            referenced_by = semantic_paper.referenced_by

            if self.references.count() < 1:
                self.add_or_create_reference_papers(references, 'references')

            if self.referenced_by.count() < 1:
                self.add_or_create_reference_papers(
                    referenced_by,
                    'referenced_by'
                )

    def add_or_create_reference_papers(self, reference_list, reference_field):
        dois = [ref['doi'] for ref in reference_list]
        doi_set = set(dois)

        existing_papers = Paper.objects.filter(doi__in=dois)
        for existing_paper in existing_papers:
            if reference_field == 'referenced_by':
                existing_paper.references.add(self)
            else:
                self.references.add(existing_paper)

        doi_hits = set(existing_papers.values_list('doi', flat=True))
        doi_misses = doi_set.difference(doi_hits)

        doi_count = len(doi_misses)
        for i, doi in enumerate(doi_misses):
            print('DOI MISS: {} / {}'.format(i, doi_count))
            if not doi:
                continue
            hubs = []
            tagline = None
            semantic_paper = SemanticScholar(doi)
            if semantic_paper is not None:
                if semantic_paper.hub_candidates is not None:
                    HUB_INSTANCE = 0
                    hubs = [
                        Hub.objects.get_or_create(
                            name=hub_name.lower()
                        )[HUB_INSTANCE]
                        for hub_name
                        in semantic_paper.hub_candidates
                    ]
                tagline = semantic_paper.abstract

            new_paper = None
            try:
                new_paper = Paper.create_manubot_paper(doi)
            except Exception as e:
                print(f'Error creating manubot paper: {e}')
                try:
                    new_paper = Paper.create_crossref_paper(doi)
                except Exception as e:
                    print(f'Error creating crossref paper: {e}')
                    pass

            if new_paper is not None:
                if not new_paper.tagline:
                    new_paper.tagline = tagline
                new_paper.hubs.add(*hubs)
                if reference_field == 'referenced_by':
                    new_paper.references.add(self)
                else:
                    self.references.add(new_paper)
                try:
                    new_paper.save()
                except Exception as e:
                    print(f'Error saving reference paper: {e}')

        self.save()


class MetadataRetrievalAttempt(models.Model):
    CROSSREF_DOI = 'CROSSREF_DOI'
    CROSSREF_QUERY = 'CROSSREF_QUERY'
    MANUBOT_DOI = 'MANUBOT_DOI'
    MANUBOT_PDF_URL = 'MANUBOT_PDF_URL'
    MANUBOT_URL = 'MANUBOT_URL'
    PARSE_PDF = 'PARSE_PDF'

    METHOD_CHOICES = [
        (CROSSREF_DOI, CROSSREF_DOI),
        (CROSSREF_QUERY, CROSSREF_QUERY),
        (MANUBOT_DOI, MANUBOT_DOI),
        (MANUBOT_PDF_URL, MANUBOT_PDF_URL),
        (MANUBOT_URL, MANUBOT_URL),
        (PARSE_PDF, PARSE_PDF),
    ]

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now_add=True)
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name='metadata_retrieval_attempts'
    )
    method = models.CharField(
        choices=METHOD_CHOICES,
        max_length=125
    )


class Figure(models.Model):
    FIGURE = 'FIGURE'
    PREVIEW = 'PREVIEW'
    FIGURE_TYPE_CHOICES = [
        (FIGURE, 'Figure'),
        (PREVIEW, 'Preview')
    ]

    file = models.FileField(
        upload_to='uploads/figures/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name='figures'
    )
    figure_type = models.CharField(choices=FIGURE_TYPE_CHOICES, max_length=16)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)


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
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
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
