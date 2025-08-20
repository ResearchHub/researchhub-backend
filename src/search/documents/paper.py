import logging
import math
from typing import override

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from paper.models import Paper
from paper.utils import format_raw_authors
from search.analyzers import title_analyzer
from utils.doi import DOI

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    citations = es_fields.IntegerField()
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField(format="yyyy-MM-dd")
    doi = es_fields.TextField(analyzer="keyword")
    openalex_id = es_fields.TextField()
    # TODO: Deprecate this field once we move over to new app. It should not longer be necessary since authors property will replace it.
    raw_authors = es_fields.ObjectField(
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    suggestion_phrases = es_fields.CompletionField()

    class Index:
        name = "paper"

    class Django:
        model = Paper
        fields = ["id"]

    @override
    def should_index_object(self, obj):  # type: ignore[override]
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

    def prepare_raw_authors(self, instance):
        authors = []
        if isinstance(instance.raw_authors, list) is False:
            return authors

        for author in instance.raw_authors:
            if isinstance(author, dict):
                authors.append(
                    {
                        "first_name": author.get("first_name"),
                        "last_name": author.get("last_name"),
                        "full_name": f'{author.get("first_name")} {author.get("last_name")}',
                    }
                )

        return authors

    def prepare_doi_indexing(self, instance):
        return instance.doi or ""
