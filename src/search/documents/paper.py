import io
import logging
import sys
import time
from typing import Any, Iterable, Optional, override

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet
from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from feed.models import FeedEntry
from paper.models import Paper
from paper.utils import format_raw_authors
from search.analyzers import content_analyzer, title_analyzer
from search.base.utils import generate_ngrams
from utils.doi import DOI

from .base import BaseDocument

logger = logging.getLogger(__name__)


@registry.register_document
class PaperDocument(BaseDocument):
    auto_refresh = True

    citations = es_fields.IntegerField()
    paper_title = es_fields.TextField(analyzer=title_analyzer)
    paper_publish_date = es_fields.DateField()
    doi = es_fields.TextField(analyzer="keyword")
    openalex_id = es_fields.TextField()
    abstract = es_fields.TextField(analyzer=content_analyzer)
    is_open_access = es_fields.BooleanField()
    # TODO: Deprecate this field once we move over to new app.
    # It should not longer be necessary since authors property will replace it.
    raw_authors = es_fields.ObjectField(
        properties={
            "first_name": es_fields.TextField(),
            "last_name": es_fields.TextField(),
            "full_name": es_fields.TextField(),
        },
    )
    hubs = es_fields.ObjectField(
        properties={
            "id": es_fields.IntegerField(),
            "name": es_fields.KeywordField(),
            "slug": es_fields.TextField(),
        },
    )
    score = es_fields.IntegerField()
    hot_score_v2 = es_fields.IntegerField()
    unified_document_id = es_fields.IntegerField()
    created_date = es_fields.DateField(attr="created_date")
    suggestion_phrases = es_fields.CompletionField()

    class Index:
        name = "paper"

    class Django:
        model = Paper
        fields = ["id"]

    @override
    def get_queryset(
        self,
        filter_: Optional[Q] = None,
        exclude: Optional[Q] = None,
        count: int = None,  # type: ignore[override]
    ) -> QuerySet:
        """
        Override get_queryset to include prefetching of relationsships.
        """
        return (
            super()
            .get_queryset(filter_=filter_, exclude=exclude, count=count)
            .select_related(
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
            )
        )

    @override
    def should_index_object(self, obj) -> bool:  # type: ignore[override]
        return not obj.is_removed

    # Used specifically for "autocomplete" style suggest feature.
    # Includes a bunch of phrases the user may search by.
    def prepare_suggestion_phrases(self, instance) -> list[dict[str, Any]]:
        hot_score_v2 = self.prepare_hot_score_v2(instance)
        weighted_inputs = []

        weighted_inputs.append(
            {
                "input": str(instance.id),
                "weight": self.calculate_phrase_weight(hot_score_v2, self.DEFAULT_WEIGHT),
            }
        )

        if instance.title:
            weighted_inputs.append(
                {
                    "input": instance.title,
                    "weight": self.calculate_phrase_weight(hot_score_v2, self.TITLE_WEIGHT),
                }
            )
            if instance.paper_title and instance.paper_title != instance.title:
                weighted_inputs.append(
                    {
                        "input": instance.paper_title,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.TITLE_WEIGHT),
                    }
                )

            title_words = instance.title.split()
            for word in title_words:
                weighted_inputs.append(
                    {
                        "input": word,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.TITLE_WORDS_WEIGHT),
                    }
                )

            bigrams = generate_ngrams(title_words, n=2)
            for bigram in bigrams:
                weighted_inputs.append(
                    {
                        "input": bigram,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.BIGRAM_WEIGHT),
                    }
                )

        if instance.doi:
            doi_variants = DOI.get_variants(instance.doi)
            for doi_variant in doi_variants:
                weighted_inputs.append(
                    {
                        "input": doi_variant,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.DOI_WEIGHT),
                    }
                )

        if instance.url:
            weighted_inputs.append(
                {
                    "input": instance.url,
                    "weight": self.calculate_phrase_weight(hot_score_v2, self.DEFAULT_WEIGHT),
                }
            )

        if instance.external_source:
            weighted_inputs.append(
                {
                    "input": instance.external_source,
                    "weight": self.calculate_phrase_weight(hot_score_v2, self.JOURNAL_WEIGHT),
                }
            )
            journal_words = instance.external_source.split(" ")
            for word in journal_words:
                weighted_inputs.append(
                    {
                        "input": word,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.JOURNAL_WEIGHT),
                    }
                )

        try:
            hub_names = self.get_hub_names(instance)
            for hub_name in hub_names:
                weighted_inputs.append(
                    {
                        "input": hub_name,
                        "weight": self.calculate_phrase_weight(hot_score_v2, self.HUB_WEIGHT),
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to prepare hubs for paper {instance.id}: {e}")

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
                        weighted_inputs.append(
                            {
                                "input": all_authors_as_str,
                                "weight": self.calculate_phrase_weight(hot_score_v2, self.AUTHOR_WEIGHT),
                            }
                        )
                        for author_name in author_names_only:
                            weighted_inputs.append(
                                {
                                    "input": author_name,
                                    "weight": self.calculate_phrase_weight(hot_score_v2, self.AUTHOR_WEIGHT),
                                }
                            )
        except Exception as e:
            logger.warning(
                f"Failed to prepare author names for paper {instance.id}: {e}"
            )

        seen = {}
        for item in weighted_inputs:
            input_str = item["input"]
            if input_str not in seen or item["weight"] > seen[input_str]["weight"]:
                seen[input_str] = item

        return list(seen.values())

    def prepare_paper_publish_date(self, instance):
        """Convert datetime to date for OpenSearch indexing."""
        if instance.paper_publish_date:
            return instance.paper_publish_date.date()
        return None

    def prepare_raw_authors(self, instance) -> list[dict[str, Any]]:
        authors = []
        if isinstance(instance.raw_authors, list) is False:
            return authors

        for author in instance.raw_authors:
            if isinstance(author, dict):
                authors.append(
                    {
                        "first_name": author.get("first_name"),
                        "last_name": author.get("last_name"),
                        "full_name": (
                            f"{author.get("first_name")} {author.get("last_name")}"
                        ),
                    }
                )

        return authors

    def prepare_doi_indexing(self, instance) -> str:
        return instance.doi or ""

    def get_hub_names(self, instance) -> list[str]:
        """
        Return flat list of hub names for indexing.
        """
        return [hub.name for hub in instance.hubs.all()]

    def prepare_hubs(self, instance) -> list[dict[str, Any]]:
        if instance.unified_document and instance.unified_document.hubs.exists():
            return [
                {
                    "id": hub.id,
                    "name": hub.name,
                    "slug": hub.slug,
                }
                for hub in instance.unified_document.hubs.all()
            ]
        return []

    def prepare_score(self, instance) -> int:
        if instance.unified_document:
            return instance.unified_document.score
        return 0

    def prepare_hot_score_v2(self, instance) -> int:
        try:
            paper_content_type = ContentType.objects.get_for_model(Paper)
            feed_entry = FeedEntry.objects.filter(
                content_type=paper_content_type,
                object_id=instance.id,
            ).first()
            if feed_entry:
                return feed_entry.hot_score_v2
        except Exception:
            pass
        return 0

    def prepare_unified_document_id(self, instance) -> int | None:
        if instance.unified_document:
            return instance.unified_document.id
        return None

    def get_indexing_queryset(
        self,
        verbose: bool = False,
        filter_: Optional[Q] = None,
        exclude: Optional[Q] = None,
        count: int = None,
        action: str = "Index",
        stdout: io.FileIO = sys.stdout,
    ) -> Iterable:
        """
        Divide the queryset into chunks. Overwrite django_opensearch_dsl default
        because it uses offsets instead of filtering by greater than pk.
        """
        chunk_size = self.django.queryset_pagination
        qs = self.get_queryset(filter_=filter_, exclude=exclude, count=count)
        qs = qs.order_by("pk") if not qs.query.is_sliced else qs
        count = qs.count()
        model = self.django.model.__name__
        action = action.present_participle.title()

        done = 0
        start = time.time()
        last_pk = None
        if verbose:
            eta = self._eta(start, done, count)
            stdout.write(f"{action} {model}: 0% ({eta})\r")

        while done < count:
            if verbose:
                pct = round(done / count * 100)
                eta = self._eta(start, done, count)
                stdout.write(f"{action} {model}: {pct}% ({eta})\r")

            if last_pk is not None:
                current_qs = qs.filter(pk__gt=last_pk)[:chunk_size]
            else:
                current_qs = qs[:chunk_size]

            # Process current chunk
            chunk_items = list(current_qs)
            if not chunk_items:
                break

            for obj in chunk_items:
                done += 1
                last_pk = obj.pk
                yield obj

        if verbose:
            stdout.write(f"{action} {count} {model}: OK          \n")
