import logging
import math

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from paper.models import Paper
from paper.utils import format_raw_authors, pdf_copyright_allows_display
from search.analyzers import content_analyzer, title_analyzer
from utils import sentry
from utils.doi import DOI

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    score = es_fields.IntegerField(attr="score_indexing")
    citations = es_fields.IntegerField()
    hot_score = es_fields.IntegerField()
    discussion_count = es_fields.IntegerField()
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(
        attr="paper_publish_date", format="yyyy-MM-dd"
    )
    paper_publish_year = es_fields.IntegerField()
    abstract = es_fields.TextField(attr="abstract_indexing", analyzer=content_analyzer)
    doi = es_fields.TextField(attr="doi_indexing", analyzer="keyword")
    openalex_id = es_fields.TextField(attr="openalex_id")
    # TODO: Deprecate this field once we move over to new app. It should not longer be necessary since authors property will replace it.
    raw_authors = es_fields.ObjectField(
        attr="raw_authors_indexing",
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    authors = es_fields.ObjectField(
        properties={
            "author_id": es_fields.IntegerField(),
            "author_position": es_fields.KeywordField(),
            "full_name": es_fields.TextField(),
        },
    )
    hubs = es_fields.ObjectField(
        attr="hubs_indexing",
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.KeywordField(),
            "slug": es_fields.TextField(),
        },
    )

    slug = es_fields.TextField()
    suggestion_phrases = es_fields.CompletionField()
    title = es_fields.TextField(
        analyzer=title_analyzer,
    )
    updated_date = es_fields.DateField()
    oa_status = es_fields.KeywordField()
    pdf_license = es_fields.KeywordField()
    external_source = es_fields.KeywordField()
    completeness_status = es_fields.KeywordField()
    can_display_pdf_license = es_fields.BooleanField()

    class Index:
        name = "paper"

    class Django:
        model = Paper
        queryset_pagination = 250
        fields = ["id"]

    def should_index_object(self, obj):
        return not obj.is_removed

    # Used specifically for "autocomplete" style suggest feature.
    # Includes a bunch of phrases the user may search by.
    def prepare_suggestion_phrases(self, instance):
        phrases = []

        phrases.append(str(instance.id))

        # Variation of title which may be searched by users
        if instance.title:
            phrases.append(instance.title)
            phrases.append(instance.paper_title)
            phrases.extend(instance.title.split())

        # Add DOI variations for search
        if instance.doi:
            phrases.extend(DOI.get_variants(instance.doi))

        if instance.url:
            phrases.append(instance.url)

        # Variation of journal name which may be searched by users
        if instance.external_source:
            journal_words = instance.external_source.split(" ")
            phrases.append(instance.external_source)
            phrases.extend(journal_words)

        # Variation of OpenAlex keywords which may be searched by users
        try:
            oa_data = instance.open_alex_raw_json
            if oa_data and "keywords" in oa_data:
                keywords = []
                for keyword_obj in oa_data["keywords"]:
                    # Handle both old format (keyword) and new format (display_name)
                    keyword = keyword_obj.get("display_name") or keyword_obj.get(
                        "keyword"
                    )
                    if keyword:
                        keywords.append(keyword)

                if keywords:
                    joined_kewords = " ".join(keywords)
                    phrases.append(joined_kewords)
                    phrases.extend(keywords)

        except Exception as e:
            logger.warning(
                f"Failed to prepare OpenAlex keywords for paper {instance.id}: {e}"
            )

        try:
            hubs_indexing_flat = instance.hubs_indexing_flat
            phrases.extend(hubs_indexing_flat)
        except Exception as e:
            logger.warning(f"Failed to prepare hubs for paper {instance.id}: {e}")

        # Variation of author names which may be searched by users
        try:
            if instance.raw_authors:
                authors_list = format_raw_authors(instance.raw_authors)
                if authors_list:
                    author_names_only = [
                        f"{author['first_name']} {author['last_name']}"
                        for author in authors_list
                        if author.get("first_name") and author.get("last_name")
                    ]
                    if author_names_only:
                        all_authors_as_str = ", ".join(author_names_only)
                        phrases.append(all_authors_as_str)
                        phrases.extend(author_names_only)
        except Exception as e:
            logger.warning(
                f"Failed to prepare author names for paper {instance.id}: {e}"
            )

        # Assign weight based on how "hot" the paper is
        weight = 1
        if instance.unified_document and instance.unified_document.hot_score > 0:
            # Scale down the hot score from 1 - 100 to avoid a huge range
            # of values that could result in bad suggestions
            weight = int(math.log(instance.unified_document.hot_score, 10) * 10)

        deduped = list(set(phrases))
        strings_only = [phrase for phrase in deduped if isinstance(phrase, str)]

        return {
            "input": strings_only,  # Dedupe using set
            "weight": weight,
        }

    def prepare_completeness_status(self, instance):
        try:
            return instance.get_paper_completeness()
        except Exception:
            logger.warning(
                f"Failed to prepare completeness status for paper {instance.id}"
            )
            return Paper.PARTIAL

    def prepare_paper_publish_year(self, instance):
        if instance.paper_publish_date:
            return instance.paper_publish_date.year
        return None

    def prepare_can_display_pdf_license(self, instance):
        try:
            return pdf_copyright_allows_display(instance)
        except Exception as e:
            logger.warning(
                f"Failed to prepare pdf license for paper {instance.id}: {e}"
            )

        return False

    def prepare_hot_score(self, instance):
        if instance.unified_document:
            return instance.unified_document.hot_score
        return 0

    def prepare_authors(self, instance):
        """
        Prepare authors data from paper authorships.
        Returns a list of authors with their IDs, positions, and names.
        """
        authors = []
        for authorship in instance.authorships.all():
            authors.append(
                {
                    "author_id": authorship.author.id,
                    "author_position": authorship.author_position,
                    "full_name": authorship.raw_author_name,
                }
            )
        return authors
