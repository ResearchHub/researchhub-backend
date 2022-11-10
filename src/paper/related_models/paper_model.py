import datetime

import pytz
import regex as re
import requests
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.postgres.fields import JSONField
from django.contrib.postgres.indexes import HashIndex
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models import Avg, Count, F, IntegerField, Q, Sum
from django.db.models.functions import Cast, Extract
from django_elasticsearch_dsl_drf.wrappers import dict_to_obj
from manubot.cite.doi import get_doi_csl_item
from manubot.cite.unpaywall import Unpaywall

import utils.sentry as sentry
from discussion.reaction_models import AbstractGenericReactionModel
from hub.models import Hub
from hub.serializers import HubSerializer
from paper.lib import journal_hosts
from paper.tasks import (
    celery_extract_figures,
    celery_extract_meta_data,
    celery_extract_pdf_preview,
    celery_extract_twitter_comments,
    celery_paper_reset_cache,
)
from paper.utils import (
    get_csl_item,
    paper_piecewise_log,
    parse_author_name,
    populate_metadata_from_crossref,
    populate_metadata_from_manubot_pdf_url,
    populate_metadata_from_manubot_url,
    populate_metadata_from_pdf,
    populate_pdf_url_from_journal_url,
)
from purchase.models import Purchase
from researchhub.lib import CREATED_LOCATIONS
from researchhub.settings import TESTING
from summary.models import Summary
from utils.arxiv import Arxiv
from utils.crossref import Crossref
from utils.http import check_url_contains_pdf
from utils.semantic_scholar import SemanticScholar
from utils.twitter import (
    get_twitter_doi_results,
    get_twitter_results,
    get_twitter_url_results,
)

DOI_IDENTIFIER = "10."
ARXIV_IDENTIFIER = "arXiv:"
HOT_SCORE_WEIGHT = 5
HELP_TEXT_IS_PUBLIC = "Hides the paper from the public."
HELP_TEXT_IS_REMOVED = "Hides the paper because it is not allowed."


class Paper(AbstractGenericReactionModel):
    REGULAR = "REGULAR"
    PRE_REGISTRATION = "PRE_REGISTRATION"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"

    PAPER_TYPE_CHOICES = [(REGULAR, REGULAR), (PRE_REGISTRATION, PRE_REGISTRATION)]
    PAPER_COMPLETENESS = [
        (COMPLETE, COMPLETE),
        (PARTIAL, PARTIAL),
        (INCOMPLETE, INCOMPLETE),
    ]

    CREATED_LOCATION_PROGRESS = CREATED_LOCATIONS["PROGRESS"]
    CREATED_LOCATION_CHOICES = [(CREATED_LOCATION_PROGRESS, "Progress")]

    twitter_score_updated_date = models.DateTimeField(null=True, blank=True)
    is_public = models.BooleanField(default=True, help_text=HELP_TEXT_IS_PUBLIC)

    # TODO clean this up to use SoftDeleteable mixin in utils
    is_removed = models.BooleanField(default=False, help_text=HELP_TEXT_IS_REMOVED)

    is_removed_by_user = models.BooleanField(
        default=False, help_text=HELP_TEXT_IS_REMOVED
    )
    bullet_low_quality = models.BooleanField(default=False)
    summary_low_quality = models.BooleanField(default=False)
    discussion_count = models.IntegerField(default=0, db_index=True)
    twitter_score = models.IntegerField(default=1)

    views = models.IntegerField(default=0)
    downloads = models.IntegerField(default=0)
    twitter_mentions = models.IntegerField(default=0)
    citations = models.IntegerField(default=0)

    # Moderators are obsolete, in favor of super mods on the user
    moderators = models.ManyToManyField(
        "user.User", related_name="moderated_papers", blank=True
    )
    authors = models.ManyToManyField(
        "user.Author",
        related_name="authored_papers",
        blank=True,
        help_text="Author that participated in the research paper",
    )
    hubs = models.ManyToManyField("hub.Hub", related_name="papers", blank=True)
    summary = models.ForeignKey(
        Summary, blank=True, null=True, related_name="papers", on_delete=models.SET_NULL
    )
    file = models.FileField(
        max_length=512,
        upload_to="uploads/papers/%Y/%m/%d",
        default=None,
        null=True,
        blank=True,
        validators=[FileExtensionValidator(["pdf"])],
    )
    pdf_file_extract = models.FileField(
        max_length=512,
        upload_to="uploads/papers/%Y/%m/%d/pdf_extract",
        default=None,
        null=True,
        blank=True,
    )
    edited_file_extract = models.FileField(
        max_length=512,
        upload_to="uploads/papers/%Y/%m/%d/edited_extract",
        default=None,
        null=True,
        blank=True,
    )
    file_created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True,
    )
    retrieved_from_external_source = models.BooleanField(default=False)
    is_open_access = models.BooleanField(default=None, null=True, blank=True)
    oa_status = models.CharField(max_length=8, default=None, null=True, blank=True)
    external_source = models.CharField(
        max_length=255, default=None, null=True, blank=True
    )
    paper_type = models.CharField(
        choices=PAPER_TYPE_CHOICES, max_length=32, default=REGULAR
    )
    completeness = models.CharField(
        choices=PAPER_COMPLETENESS, max_length=16, default=INCOMPLETE
    )

    # User generated
    title = models.CharField(max_length=1024)  # User generated title
    tagline = models.CharField(max_length=255, default=None, null=True, blank=True)
    uploaded_by = models.ForeignKey(
        "user.User",
        related_name="papers",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        help_text=(
            "RH User account that submitted this paper. "
            + "NOTE: user didnt necessarily had to be the author"
        ),
    )

    # Metadata
    doi = models.CharField(
        max_length=255, default=None, null=True, blank=True, unique=True
    )
    alternate_ids = JSONField(
        default=dict,
        blank=True,
    )
    paper_title = models.CharField(  # Official paper title
        max_length=1024, default=None, null=True, blank=True
    )
    paper_publish_date = models.DateField(null=True, blank=True)
    raw_authors = JSONField(blank=True, null=True)
    abstract = models.TextField(default=None, null=True, blank=True)
    publication_type = models.CharField(
        max_length=255, default=None, null=True, blank=True
    )
    references = models.ManyToManyField(
        "self", symmetrical=False, related_name="referenced_by", blank=True
    )
    # Can be the url entered by users during upload (seed URL)
    url = models.URLField(
        max_length=1024, default=None, null=True, blank=True, unique=True
    )
    pdf_url = models.URLField(
        max_length=1024,
        default=None,
        null=True,
        blank=True,
    )
    pdf_license = models.CharField(max_length=255, default=None, null=True, blank=True)
    pdf_license_url = models.URLField(
        max_length=1024, default=None, null=True, blank=True
    )
    csl_item = JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="bibliographic metadata as a single "
        "Citation Styles Language JSON item.",
    )
    oa_pdf_location = JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="PDF availability in Unpaywall OA Location format.",
    )
    external_metadata = JSONField(null=True, blank=True)

    purchases = GenericRelation(
        "purchase.Purchase",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="paper",
    )

    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="papers",
    )
    # Slug is automatically generated on a signal, so it is not needed in a form
    slug = models.SlugField(max_length=1024, blank=True)
    unified_document = models.OneToOneField(
        "researchhub_document.ResearchhubUnifiedDocument",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="paper",
    )

    class Meta:
        indexes = (
            HashIndex(fields=("url",), name="paper_paper_url_hix"),
            HashIndex(fields=("pdf_url",), name="paper_paper_pdf_url_hix"),
        )

    def __str__(self):
        title = self.title
        uploaded_by = self.uploaded_by
        if title and uploaded_by:
            return "{} - {}".format(title, uploaded_by)
        elif title:
            return title
        else:
            return "titleless paper"

    @property
    def display_title(self):
        return self.title or self.paper_title

    @property
    def uploaded_date(self):
        return self.created_date

    @property
    def created_by(self):
        return self.uploaded_by

    @property
    def is_hidden(self):
        return (not self.is_public) or self.is_removed or self.is_removed_by_user

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

    @property
    def raw_authors_indexing(self):
        authors = []
        if isinstance(self.raw_authors, list) is False:
            return authors

        for author in self.raw_authors:
            if isinstance(author, dict):
                authors.append(
                    {
                        "first_name": author.get("first_name"),
                        "last_name": author.get("last_name"),
                        "full_name": f'{author.get("first_name")} {author.get("last_name")}',
                    }
                )

        return authors

    @property
    def authors_indexing(self):
        return [parse_author_name(author) for author in self.authors.all()]

    @property
    def discussion_count_indexing(self):
        """Number of discussions."""
        return self.get_discussion_count()

    @property
    def hubs_indexing(self):
        return [HubSerializer(h).data for h in self.hubs.all()]

    @property
    def hubs_indexing_flat(self):
        return [hub.name for hub in self.hubs.all()]

    @property
    def summary_indexing(self):
        if self.summary:
            return self.summary.summary_plain_text
        return ""

    @property
    def abstract_indexing(self):
        return self.abstract if self.abstract else ""

    @property
    def doi_indexing(self):
        return self.doi or ""

    @property
    def hot_score(self):
        if self.unified_document is None:
            return self.score
        return self.unified_document.hot_score

    @property
    def hot_score_v2(self):
        if self.unified_document is None:
            return self.score
        return self.unified_document.hot_score_v2

    @property
    def votes_indexing(self):
        all_votes = self.votes.all()
        if len(all_votes) > 0:
            return [self.get_vote_for_index(vote) for vote in all_votes]
        return {}

    def true_author_count(self):
        registered_author_count = self.authors.count()
        raw_author_count = 0

        if isinstance(self.raw_authors, list):
            raw_author_count = len(self.raw_authors)
            for author in self.raw_authors:
                if self.authors.filter(
                    first_name=author.get("first_name"),
                    last_name=author.get("last_name"),
                ).exists():
                    raw_author_count -= 1

        return raw_author_count + registered_author_count

    def get_hub_names(self):
        return ",".join(self.hubs.values_list("name", flat=True))

    def get_accepted_answer(self):
        return self.threads.filter(
            is_accepted_answer=True, discussion_post_type="ANSWER"
        ).first()

    def calculate_hot_score(paper):
        ALGO_START_UNIX = 1546329600
        TWITTER_BOOST = 100
        TIME_DIV = 3600000
        HOUR_SECONDS = 86400
        DATE_BOOST = 10

        boosts = paper.purchases.filter(
            paid_status=Purchase.PAID,
            amount__gt=0,
            user__moderator=True,
            boost_time__gte=0,
        )
        today = datetime.datetime.now(tz=pytz.utc).replace(hour=0, minute=0, second=0)
        score = paper.score
        if score is None:
            return 0

        unified_doc = paper.unified_document
        if unified_doc is None:
            return score

        original_uploaded_date = paper.created_date
        uploaded_date = original_uploaded_date
        twitter_score = paper.twitter_score
        day_delta = datetime.timedelta(days=2)
        timeframe = today - day_delta

        if original_uploaded_date > timeframe:
            uploaded_date = timeframe.replace(
                hour=original_uploaded_date.hour,
                minute=original_uploaded_date.minute,
                second=original_uploaded_date.second,
            )

        votes = paper.votes
        if votes.exists():
            vote_avg_epoch = (
                paper.votes.aggregate(
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

        twitter_boost_score = 0
        if twitter_score > 0:
            twitter_epoch = (uploaded_date.timestamp() - ALGO_START_UNIX) / TIME_DIV
            twitter_boost_score = (
                paper_piecewise_log(twitter_score + 1) * TWITTER_BOOST
            ) / twitter_epoch

        vote_avg = (max(0, vote_avg_epoch - ALGO_START_UNIX)) / TIME_DIV

        base_score = paper_piecewise_log(score + 1)
        uploaded_date_score = uploaded_date.timestamp() / TIME_DIV
        vote_score = paper_piecewise_log(num_votes + 1)
        discussion_score = paper_piecewise_log(paper.discussion_count + 1)

        # Why we log delta days
        # Ex: If paper 1 was uploaded 3 days ago with a low score and paper
        # 2 was uploaded 4 days ago with a very high score, paper 2 will
        # appear higher in the feed than paper 1. If we remove the delta
        # days log, paper 1 will appear higher just because time is linear,
        # and it gives a it better score

        if original_uploaded_date > timeframe:
            uploaded_date_delta = original_uploaded_date - timeframe
            delta_days = (
                paper_piecewise_log(uploaded_date_delta.total_seconds() / HOUR_SECONDS)
                * DATE_BOOST
            )
            uploaded_date_score += delta_days
        else:
            uploaded_date_delta = timeframe - original_uploaded_date
            delta_days = (
                -paper_piecewise_log(
                    (uploaded_date_delta.total_seconds() / HOUR_SECONDS) + 1
                )
                * DATE_BOOST
            )
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
            + twitter_boost_score
            + boost_score
        ) * 1000

        completeness = paper.completeness
        if completeness == paper.COMPLETE:
            hot_score *= 1
        elif completeness == paper.PARTIAL:
            hot_score *= 0.95
        else:
            hot_score *= 0.90

        unified_doc.hot_score = hot_score
        paper.save()
        return hot_score

    def calculate_twitter_score(self):
        result_ids = set()
        paper_title = self.paper_title
        url = self.url
        doi = self.doi

        if doi:
            doi_results = set(
                {
                    res.user.name: res.id
                    for res in get_twitter_doi_results(self.doi, filters="")
                }.values()
            )
            result_ids |= doi_results

        if url:
            url_results = set(
                {
                    res.user.name: res.id
                    for res in get_twitter_url_results(self.url, filters="")
                }.values()
            )
            result_ids |= url_results

        if paper_title:
            title_results = set(
                {
                    res.user.name: res.id
                    for res in get_twitter_results(self.paper_title)
                }.values()
            )
            result_ids |= title_results

        self.twitter_score_updated_date = datetime.datetime.now()
        self.twitter_score = len(result_ids) + 1
        self.twitter_mentions = self.twitter_score
        self.save()
        return self.twitter_score

    def get_promoted_score(paper):
        purchases = paper.purchases.filter(
            paid_status=Purchase.PAID, amount__gt=0, boost_time__gt=0
        )
        if purchases.exists():
            base_score = paper.score
            boost_amount = (
                purchases.annotate(amount_as_int=Cast("amount", IntegerField()))
                .aggregate(sum=Sum("amount_as_int"))
                .get("sum", 0)
            )
            return base_score + boost_amount
        return False

    def get_discussion_count(self):
        from discussion.models import Thread

        sources = [Thread.RESEARCHHUB, Thread.INLINE_ABSTRACT, Thread.INLINE_PAPER_BODY]

        thread_count = self.threads.aggregate(
            discussion_count=Count(
                1,
                filter=Q(
                    is_removed=False, created_by__isnull=False, source__in=sources
                ),
            )
        )["discussion_count"]
        comment_count = self.threads.aggregate(
            discussion_count=Count(
                "comments",
                filter=Q(
                    comments__is_removed=False,
                    comments__created_by__isnull=False,
                    source__in=sources,
                ),
            )
        )["discussion_count"]
        reply_count = self.threads.aggregate(
            discussion_count=Count(
                "comments__replies",
                filter=Q(
                    comments__replies__is_removed=False,
                    comments__replies__created_by__isnull=False,
                    source__in=sources,
                ),
            )
        )["discussion_count"]
        return thread_count + comment_count + reply_count

    def extract_figures(self, use_celery=True):
        # TODO: Make figure more consistent - temporarily removing figures
        return
        if TESTING:
            return

        if use_celery:
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

        if use_celery:
            celery_extract_pdf_preview.apply_async(
                (self.id,),
                priority=2,
                countdown=10,
            )
        else:
            celery_extract_pdf_preview(self.id)

    def check_doi(self):
        # For url uploads, checks if url is in allowed hosts
        for journal_host in journal_hosts:
            if self.url and journal_host in self.url:
                return
            if self.pdf_url and journal_host in self.pdf_url:
                return

        regex = r"(.*doi\.org\/)(.*)"
        doi = self.doi or ""

        regex_doi = re.search(regex, doi)
        if regex_doi and len(regex_doi.groups()) > 1:
            doi = regex_doi.groups()[-1]

        has_doi = doi.startswith(DOI_IDENTIFIER)
        has_arxiv = doi.startswith(ARXIV_IDENTIFIER)

        # For pdf uploads, checks if doi has an arxiv identifer
        if has_arxiv:
            return

        if not doi:
            self.is_removed = True

        res = requests.get(
            "https://doi.org/api/handles/{}".format(doi),
            headers=requests.utils.default_headers(),
        )
        if res.status_code >= 200 and res.status_code < 400 and has_doi:
            self.is_removed = False
        else:
            self.is_removed = True

        # self.save(update_fields['is_removed'])
        self.save()
        return self.is_removed

    def extract_meta_data(self, title=None, check_title=False, use_celery=True):
        if TESTING:
            return

        if title is None and self.paper_title:
            title = self.paper_title
        elif title is None and self.title:
            title = self.title
        elif title is None:
            return

        if use_celery:
            celery_extract_meta_data.apply_async(
                (self.id, title, check_title),
                priority=1,
                countdown=10,
            )
        else:
            celery_extract_meta_data(self.id, title, check_title)

    def extract_twitter_comments(self, use_celery=True):
        if TESTING:
            return

        if use_celery:
            celery_extract_twitter_comments.apply_async(
                (self.id,),
                priority=5,
                countdown=10,
            )
        else:
            celery_extract_twitter_comments(self.id)

    def get_vote_for_index(self, vote):
        wrapper = dict_to_obj(
            {
                "vote_type": vote.vote_type,
                "updated_date": vote.updated_date,
            }
        )

        return wrapper

    def update_summary(self, summary):
        self.summary = summary
        self.save()

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

    def reset_cache(self, use_celery=True):
        if use_celery:
            celery_paper_reset_cache.apply_async((self.id,), priority=2)
        else:
            celery_paper_reset_cache(self.id)

    def get_license(self, save=True):
        pdf_license = self.pdf_license
        if pdf_license:
            return pdf_license

        csl_item = self.csl_item
        retrieved_csl = False
        if not csl_item:
            fields = ["doi", "url", "pdf_url"]
            for field in fields:
                item = getattr(self, field)
                if not item:
                    continue
                try:
                    if field == "doi":
                        csl_item = get_doi_csl_item(item)
                    else:
                        csl_item = get_csl_item(item)

                    if csl_item:
                        retrieved_csl = True
                        break
                except Exception as e:
                    sentry.log_error(e)

        if not csl_item:
            return None

        if retrieved_csl and save:
            self.csl_item = csl_item
            self.save()

        best_openly_licensed_pdf = {}
        try:
            unpaywall = Unpaywall.from_csl_item(csl_item)
            best_openly_licensed_pdf = unpaywall.best_openly_licensed_pdf
        except Exception as e:
            sentry.log_error(e)

        if not best_openly_licensed_pdf:
            return None

        license = best_openly_licensed_pdf.get("license", None)
        if save:
            self.pdf_license = license
            self.save()
        return license

    def set_paper_completeness(self):
        if self.abstract and self.file:
            self.completeness = self.COMPLETE
        elif self.abstract or self.file:
            self.completeness = self.PARTIAL
        else:
            self.completeness = self.INCOMPLETE
        self.save()

    def get_pdf_link(self, should_save=False):
        metadata, converted = populate_pdf_url_from_journal_url(self.url, {})
        pdf_url = metadata.get("pdf_url")
        if pdf_url:
            self.pdf_url = metadata.get("pdf_url")
            if should_save:
                self.save()
        return metadata, converted


class MetadataRetrievalAttempt(models.Model):
    CROSSREF_DOI = "CROSSREF_DOI"
    CROSSREF_QUERY = "CROSSREF_QUERY"
    MANUBOT_DOI = "MANUBOT_DOI"
    MANUBOT_PDF_URL = "MANUBOT_PDF_URL"
    MANUBOT_URL = "MANUBOT_URL"
    PARSE_PDF = "PARSE_PDF"
    PDF_FROM_URL = "PDF_FROM_URL"

    METHOD_CHOICES = [
        (CROSSREF_DOI, CROSSREF_DOI),
        (CROSSREF_QUERY, CROSSREF_QUERY),
        (MANUBOT_DOI, MANUBOT_DOI),
        (MANUBOT_PDF_URL, MANUBOT_PDF_URL),
        (MANUBOT_URL, MANUBOT_URL),
        (PARSE_PDF, PARSE_PDF),
        (PDF_FROM_URL, PDF_FROM_URL),
    ]

    POPULATE_METADATA_METHODS = {
        MANUBOT_URL: populate_metadata_from_manubot_url,
        MANUBOT_PDF_URL: populate_metadata_from_manubot_pdf_url,
        PDF_FROM_URL: populate_pdf_url_from_journal_url,
        PARSE_PDF: populate_metadata_from_pdf,
        CROSSREF_QUERY: populate_metadata_from_crossref,
    }

    # TODO use mixin here
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now_add=True)
    paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="metadata_retrieval_attempts"
    )
    method = models.CharField(choices=METHOD_CHOICES, max_length=125)

    @classmethod
    def get_url_method_priority_list(cls, url):
        """
        Evaluates the url and returns the methods in the order they should be
        attempted to retrieve metadata.
        """
        methods = []
        if check_url_contains_pdf(url):
            methods.append(cls.MANUBOT_PDF_URL)
            # TODO: Create util functions for these methods
            methods.append(cls.PARSE_PDF)
            methods.append(cls.CROSSREF_QUERY)
        else:
            methods.append(cls.PDF_FROM_URL)
            # methods.append(cls.MANUBOT_PDF_URL)
            methods.append(cls.MANUBOT_URL)
        return methods


class Figure(models.Model):
    FIGURE = "FIGURE"
    PREVIEW = "PREVIEW"
    FIGURE_TYPE_CHOICES = [(FIGURE, "Figure"), (PREVIEW, "Preview")]

    CREATED_LOCATION_PROGRESS = CREATED_LOCATIONS["PROGRESS"]
    CREATED_LOCATION_CHOICES = [(CREATED_LOCATION_PROGRESS, "Progress")]

    file = models.FileField(
        upload_to="uploads/figures/%Y/%m/%d", default=None, null=True, blank=True
    )
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="figures")
    figure_type = models.CharField(choices=FIGURE_TYPE_CHOICES, max_length=16)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "user.User", on_delete=models.SET_NULL, related_name="figures", null=True
    )
    created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True,
    )


# TODO: calvinhlee - remove this model once migration is confirmed to be good.
class Vote(models.Model):
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (UPVOTE, "Upvote"),
        (DOWNVOTE, "Downvote"),
    ]
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="votes_legacy",
        related_query_name="vote_legacy",
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="paper_votes",
        related_query_name="paper_vote",
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_date = models.DateTimeField(auto_now=True, db_index=True)
    vote_type = models.IntegerField(choices=VOTE_TYPE_CHOICES)
    is_removed = models.BooleanField(default=False, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "created_by"], name="unique_paper_vote"
            )
        ]

    def __str__(self):
        return "{} - {}".format(self.created_by, self.vote_type)


# TODO: calvinhlee - remove this model once migration is confirmed to be good.
class Flag(models.Model):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="flags_legacy",
        related_query_name="flag_legacy",
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="paper_flags",
        related_query_name="paper_flag",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "created_by"], name="unique_paper_flag"
            )
        ]


class AdditionalFile(models.Model):
    file = models.FileField(
        max_length=1024,
        upload_to="uploads/paper_additional_files/%Y/%m/%d",
        default=None,
        null=True,
        blank=True,
    )
    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="additional_files",
        related_query_name="additional_file",
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paper_additional_files",
        related_query_name="paper_additional_file",
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
