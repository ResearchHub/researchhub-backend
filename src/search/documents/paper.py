import math

from django_elasticsearch_dsl import Document, Index
from django_elasticsearch_dsl import fields
from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter, tokenizer

from paper.models import Paper
from paper.utils import format_raw_authors, pdf_copyright_allows_display
from search.analyzers import content_analyzer, name_analyzer, title_analyzer
from utils import sentry

from .base import BaseDocument


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    score = es_fields.IntegerField(attr="score_indexing")
    citations = es_fields.IntegerField()
    citation_percentile = es_fields.FloatField(attr="citation_percentile")
    hot_score = es_fields.IntegerField()
    discussion_count = es_fields.IntegerField()
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(
        attr="paper_publish_date", format="yyyy-MM-dd"
    )
    paper_publish_year = es_fields.IntegerField()
    abstract = es_fields.TextField(attr="abstract_indexing", analyzer=content_analyzer)
    doi = es_fields.TextField(attr="doi_indexing", analyzer="keyword")
    raw_authors = es_fields.ObjectField(
        attr="raw_authors_indexing",
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
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
    suggestion_phrases = es_fields.Completion()
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

    def should_remove_from_index(self, obj):
        if obj.is_removed:
            return True

        return False

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

        if instance.doi:
            phrases.append(instance.doi)

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
            keywords = [keyword_obj["keyword"] for keyword_obj in oa_data["keywords"]]
            joined_kewords = " ".join(keywords)

            phrases.append(joined_kewords)
            phrases.extend(keywords)

        except Exception:
            pass

        try:
            hubs_indexing_flat = instance.hubs_indexing_flat
            phrases.extend(hubs_indexing_flat)
        except Exception:
            pass

        # Variation of author names which may be searched by users
        try:
            authors_list = format_raw_authors(instance.raw_authors)
            author_names_only = [
                f"{author['first_name']} {author['last_name']}"
                for author in authors_list
                if author["first_name"] and author["last_name"]
            ]
            all_authors_as_str = ", ".join(author_names_only)

            phrases.append(all_authors_as_str)
            phrases.extend(author_names_only)
        except Exception:
            pass

        # Assign weight based on how "hot" the paper is
        weight = 1
        if instance.unified_document.hot_score_v2 > 0:
            # Scale down the hot score from 1 - 100 to avoid a huge range
            # of values that could result in bad suggestions
            weight = int(math.log(instance.unified_document.hot_score_v2, 10) * 10)

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
            return Paper.PARTIAL

    def prepare_paper_publish_year(self, instance):
        if instance.paper_publish_date:
            return instance.paper_publish_date.year
        return None

    def prepare_can_display_pdf_license(self, instance):
        try:
            return pdf_copyright_allows_display(instance)
        except Exception:
            pass

        return False

    def prepare_hot_score(self, instance):
        if instance.unified_document:
            return instance.unified_document.hot_score_v2
        return 0

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
            data["suggestion_phrases"] = self.prepare_suggestion_phrases(instance)
            return data
        except Exception as error:
            sentry.log_error(error)
            return False
