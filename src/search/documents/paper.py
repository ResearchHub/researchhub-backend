import math

from django_elasticsearch_dsl import Document, Index
from django_elasticsearch_dsl import fields
from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter, tokenizer

from paper.models import Paper
from paper.utils import format_raw_authors
from search.analyzers import content_analyzer, name_analyzer, title_analyzer
from utils import sentry

from .base import BaseDocument


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    hubs_flat = es_fields.TextField(attr="hubs_indexing_flat")
    discussion_count = es_fields.IntegerField(attr="discussion_count_indexing")
    score = es_fields.IntegerField(attr="score_indexing")
    hot_score = es_fields.IntegerField(attr="hot_score_indexing")
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(
        attr="paper_publish_date", format="yyyy-MM-dd"
    )
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
    is_open_access = es_fields.BooleanField()
    oa_status = es_fields.KeywordField()
    pdf_license = es_fields.KeywordField()
    external_source = es_fields.KeywordField()

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

        # Variation of title which may be searched by users
        if instance.title:
            phrases.append(instance.title)
            phrases.extend(instance.title.split())

        if instance.doi:
            phrases.append(instance.doi)

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

        except:
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
        except:
            pass

        # Assign weight based on how "hot" the paper is
        weight = 1
        if instance.unified_document.hot_score_v2 > 0:
            # Scale down the hot score from 1 - 100 to avoid a huge range
            # of values that could result in bad suggestions
            weight = int(math.log(instance.unified_document.hot_score_v2, 10) * 10)

        return {
            "input": list(set(phrases)),  # Dedupe using set
            "weight": weight,
        }

    def prepare(self, instance):
        try:
            data = super().prepare(instance)
            data["suggestion_phrases"] = self.prepare_suggestion_phrases(instance)
            return data
        except Exception as error:
            print("Paper Indexing error: ", error, "Instance: ", instance.id)
            sentry.log_error(error)
            return False
