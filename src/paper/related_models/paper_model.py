import regex as re
import requests
from bs4 import BeautifulSoup
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import HashIndex
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Func, Index, IntegerField, JSONField, Sum
from django.db.models.functions import Cast
from manubot.cite.doi import get_doi_csl_item
from manubot.cite.unpaywall import Unpaywall

import utils.sentry as sentry
from discussion.models import AbstractGenericReactionModel, Vote
from hub.models import Hub
from hub.serializers import DynamicHubSerializer
from paper.lib import journal_hosts
from paper.related_models.citation_model import Citation
from paper.tasks import celery_extract_meta_data, celery_extract_pdf_preview
from paper.utils import (
    get_csl_item,
    parse_author_name,
    populate_pdf_url_from_journal_url,
)
from purchase.models import Purchase
from reputation.models import Score, ScoreChange
from reputation.related_models.paper_reward import HubCitationValue
from researchhub.lib import CREATED_LOCATIONS
from researchhub.settings import TESTING
from researchhub_comment.models import RhCommentThreadModel
from researchhub_document.related_models.constants.editor_type import (
    EDITOR_TYPES,
    TEXT_FIELD,
)
from utils.aws import lambda_compress_and_linearize_pdf
from utils.http import scraper_get_url

DOI_IDENTIFIER = "10."
ARXIV_IDENTIFIER = "arXiv:"
HOT_SCORE_WEIGHT = 5
HELP_TEXT_IS_PUBLIC = "Hides the paper from the public."
HELP_TEXT_IS_REMOVED = "Hides the paper because it is not allowed."
HELP_TEXT_IS_PDF_REMOVED = "Hides the PDF because it infringes Copyright."


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

    rh_threads = GenericRelation(
        RhCommentThreadModel,
        help_text="New Comment-Thread module as of Jan 2023",
        related_query_name="paper",
    )
    is_public = models.BooleanField(default=True, help_text=HELP_TEXT_IS_PUBLIC)

    # TODO clean this up to use SoftDeleteable mixin in utils
    is_removed = models.BooleanField(default=False, help_text=HELP_TEXT_IS_REMOVED)

    # We assume that is_pdf_removed_by_moderator is only set to True if the PDF was removed for copyright reasons
    is_pdf_removed_by_moderator = models.BooleanField(
        default=False, help_text=HELP_TEXT_IS_PDF_REMOVED
    )
    discussion_count = models.IntegerField(default=0, db_index=True)

    views = models.IntegerField(default=0)
    citations = models.IntegerField(default=0)
    open_alex_raw_json = models.JSONField(null=True, blank=True)
    automated_bounty_created = models.BooleanField(default=False)

    authors = models.ManyToManyField(
        "user.Author",
        through="Authorship",
        related_name="papers",
        blank=True,
        help_text="Authors that participated in the research paper",
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
    paper_title = models.CharField(  # Official paper title
        max_length=1024, default=None, null=True, blank=True
    )
    paper_publish_date = models.DateField(null=True, blank=True)
    raw_authors = JSONField(blank=True, null=True)
    abstract = models.TextField(default=None, null=True, blank=True)
    abstract_src = models.FileField(
        blank=True,
        default=None,
        help_text="""
            Abstract_src is different field than abstract field.
            Abstract is legacy text field where as abstract_src field is a src field that is
            intended to be used along with different types of text editors from the frontend.
        """,
        max_length=512,
        null=True,
        upload_to="uploads/paper_abstract_src/%Y/%m/%d/",
    )
    abstract_src_type = models.CharField(
        blank=False,
        choices=EDITOR_TYPES,
        default=TEXT_FIELD,
        help_text="Indicates which text editor was used for abstract section.",
        max_length=32,
        null=True,
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
    # This is already inherited from the base class
    # but is required to set the related lookup name
    votes = GenericRelation(Vote, related_query_name="related_paper")

    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="papers",
    )
    slug = models.SlugField(
        max_length=1024,
        blank=True,
        help_text="Slug is automatically generated on a signal, so it is not needed in a form",
    )
    unified_document = models.OneToOneField(
        "researchhub_document.ResearchhubUnifiedDocument",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="paper",
    )

    # https://docs.openalex.org/api-entities/works/work-object#type
    work_type = models.CharField(
        blank=True,
        null=True,
        max_length=100,
    )

    # https://docs.openalex.org/api-entities/works/work-object#id
    openalex_id = models.CharField(
        blank=True,
        null=True,
        unique=True,
        max_length=255,
    )

    # https://docs.openalex.org/api-entities/works/work-object#language
    language = models.CharField(
        blank=True,
        null=True,
        max_length=10,
    )

    paper_series = models.ForeignKey(
        "PaperSeries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="papers",
    )

    class Meta:
        indexes = (
            HashIndex(fields=("url",), name="paper_paper_url_hix"),
            HashIndex(fields=("pdf_url",), name="paper_paper_pdf_url_hix"),
            Index(Func("doi", function="UPPER"), name="paper_paper_doi_upper_idx"),
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
    def users_to_notify(self):
        users = []
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
        serializer = DynamicHubSerializer(
            self.hubs.all(),
            many=True,
            context={},
            _include_fields=[
                "id",
                "name",
                "slug",
            ],
        )

        return serializer.data

    @property
    def hubs_indexing_flat(self):
        return [hub.name for hub in self.hubs.all()]

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

    def raw_author_count(self):
        raw_author_count = 0

        if isinstance(self.raw_authors, list):
            raw_author_count = len(self.raw_authors)
            for author in self.raw_authors:
                if self.authors.filter(
                    first_name=author.get("first_name"),
                    last_name=author.get("last_name"),
                ).exists():
                    raw_author_count -= 1
        return raw_author_count

    def get_hub_names(self):
        return ",".join(self.hubs.values_list("name", flat=True))

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
        from paper.services.paper_version_service import PaperService

        if hasattr(self, "version") and self.version is not None:
            paper_service = PaperService()
            all_paper_versions = paper_service.get_all_paper_versions(self.id)

            paper_content_type = ContentType.objects.get_for_model(self)

            thread_queryset = RhCommentThreadModel.objects.filter(
                content_type=paper_content_type,
                object_id__in=all_paper_versions.values_list("id", flat=True),
            )

            return thread_queryset.get_discussion_count()

        # Default behavior: only count threads from this paper
        return self.rh_threads.get_discussion_count()

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
        self.completeness = self.get_paper_completeness()
        self.save()

    def get_paper_completeness(self):
        if self.abstract and self.title and (self.file or self.pdf_url):
            return self.COMPLETE
        elif self.abstract and self.title:
            return self.PARTIAL
        else:
            return self.INCOMPLETE

    def get_abstract_backup(self, should_save=False):
        if not self.abstract:
            if self.url and "cell.com" in self.url:
                try:
                    url_resp = scraper_get_url(self.url)
                    soup = BeautifulSoup(url_resp.text, "lxml")
                    summary = soup.find(
                        "h2", {"data-left-hand-nav": "Summary"}
                    ).find_next_sibling()
                    summary.find("h3").decompose()
                    summary.find("div", {"class": "mediaPlayer"}).decompose()
                except Exception as e:
                    sentry.log_error(e)
                    return None

                self.abstract = summary.text

                if should_save:
                    self.save()

                return self.abstract
        return None

    def get_pdf_link(self, should_save=False):
        if not self.url:
            return None, None

        metadata, converted = populate_pdf_url_from_journal_url(self.url, {})
        pdf_url = metadata.get("pdf_url")
        if pdf_url:
            self.pdf_url = metadata.get("pdf_url")
            if should_save:
                self.save()
        return metadata, converted

    def compress_and_linearize_file(self):
        file = self.file
        if not file:
            return

        key = file.name
        file_name = key.split("/")[-1]
        return lambda_compress_and_linearize_pdf(key, file_name)

    def update_scores_citations(self, author):
        hub = self.unified_document.get_primary_hub()
        if hub is None:
            print(f"Paper {self.id} has no primary hub")
            return

        citation_entries = Citation.objects.filter(paper=self).order_by("created_date")
        content_type = ContentType.objects.get_for_model(Citation)
        score = Score.get_or_create_score(author=author, hub=hub)

        recent_citations_score = ScoreChange.get_latest_score_change_objects(
            score,
            citation_entries.values_list("id", flat=True),
            content_type,
        )
        if recent_citations_score:
            citation_entries = [
                citation
                for citation in citation_entries
                if citation.created_date > recent_citations_score.created_date
            ]

        for citation in citation_entries:
            citation_change = citation.citation_change
            if citation_change == 0:
                continue

            Score.update_score_citations(
                author,
                hub,
                citation_change,
                citation.id,
                self.work_type,
            )

    @property
    def paper_rewards(self):
        return HubCitationValue.calculate_base_claim_rsc_reward(self)

    @property
    def hubs(self):
        """
        Access hubs through the unified document.
        This property maintains backwards compatibility while enforcing the unified document
        as the single source of truth for hubs.
        """
        if self.unified_document:
            return self.unified_document.hubs
        return Hub.objects.none()


class PaperFetchLog(models.Model):
    """
    Stores the logs for e.g. daily paper fetches from openalex
    """

    OPENALEX = "OPENALEX"
    SOURCE_CHOICES = [(OPENALEX, OPENALEX)]

    FETCH_NEW = "FETCH_NEW"
    FETCH_UPDATE = "FETCH_UPDATE"
    FETCH_TYPE_CHOICES = [(FETCH_NEW, FETCH_NEW), (FETCH_UPDATE, FETCH_UPDATE)]

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    STATUS_CHOICES = [(SUCCESS, SUCCESS), (FAILED, FAILED), (PENDING, PENDING)]

    JOURNAL_BIORXIV = "BIORXIV"
    JOURNAL_MEDRXIV = "MEDRXIV"
    JOURNAL_ARXIV = "ARXIV"
    JOURNAL_CHEMRXIV = "CHEMRXIV"
    JOURNAL_RESEARCH_SQUARE = "RESEARCH_SQUARE"
    JOURNAL_OSF = "OSF"
    JOURNAL_PEERJ = "PEERJ"
    JOURNAL_AUTHOREA = "AUTHOREA"
    JOURNAL_SSRN = "SSRN"
    JOURNAL_CHOICES = [
        (JOURNAL_BIORXIV, JOURNAL_BIORXIV),
        (JOURNAL_MEDRXIV, JOURNAL_MEDRXIV),
        (JOURNAL_ARXIV, JOURNAL_ARXIV),
        (JOURNAL_CHEMRXIV, JOURNAL_CHEMRXIV),
        (JOURNAL_RESEARCH_SQUARE, JOURNAL_RESEARCH_SQUARE),
        (JOURNAL_OSF, JOURNAL_OSF),
        (JOURNAL_PEERJ, JOURNAL_PEERJ),
        (JOURNAL_AUTHOREA, JOURNAL_AUTHOREA),
        (JOURNAL_SSRN, JOURNAL_SSRN),
    ]

    started_date = models.DateTimeField(auto_now_add=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    fetch_since_date = models.DateTimeField(null=True, blank=True)
    updated_date = models.DateTimeField(auto_now=True)

    source = models.CharField(choices=SOURCE_CHOICES, max_length=255)
    fetch_type = models.CharField(choices=FETCH_TYPE_CHOICES, max_length=255)
    status = models.CharField(choices=STATUS_CHOICES, max_length=255)

    total_papers_processed = models.IntegerField(default=0)
    next_cursor = models.CharField(max_length=255, null=True, blank=True)

    journal = models.CharField(
        choices=JOURNAL_CHOICES, max_length=255, null=True, blank=True
    )


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

    class Meta:
        indexes = [
            models.Index(fields=["paper", "figure_type"], name="figure_paper_type_idx"),
        ]
