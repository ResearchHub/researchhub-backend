import io
import json
import logging
import math
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
            "namespace": es_fields.KeywordField(),
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
    def prepare_suggestion_phrases(self, instance) -> dict[str, Any]:
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
        try:
            journal_name = self._get_journal_name_from_hubs(instance)
            if journal_name:
                journal_words = journal_name.split(" ")
                phrases.append(journal_name)
                phrases.extend(journal_words)
        except Exception as e:
            logger.warning(
                f"Failed to prepare journal phrases for paper {instance.id}: {e}"
            )

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
            hub_names = self.get_hub_names(instance)
            phrases.extend(hub_names)
        except Exception as e:
            logger.warning(f"Failed to prepare hubs for paper {instance.id}: {e}")

        # Variation of author names which may be searched by users
        try:
            if instance.raw_authors:
                authors_list = self._prepare_authors_for_suggestions(instance)
                if authors_list:
                    author_names_only = [
                        (
                            f"{author.get('first_name', '')} "
                            f"{author.get('last_name', '')}"
                        ).strip()
                        for author in authors_list
                        if author.get("first_name") or author.get("last_name")
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
        hot_score_v2 = self.prepare_hot_score_v2(instance)
        if hot_score_v2 > 0:
            # Scale down the hot score to avoid a huge range
            # of values that could result in bad suggestions
            weight = int(math.log(hot_score_v2, 10) * 10)

        deduped = list(set(phrases))
        strings_only = [phrase for phrase in deduped if isinstance(phrase, str)]

        return {
            "input": strings_only,  # Dedupe using set
            "weight": weight,
        }

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

    def _prepare_authors_for_suggestions(self, instance) -> list[dict[str, Any]]:
        """
        Prepare authors for suggestion phrases, handling various raw_authors formats.

        Handles:
        - JSON strings (parses them)
        - Lists of JSON strings (parses each)
        - Lists of dicts in raw format (transforms with format_raw_authors)
        - Lists of dicts already formatted (uses directly)
        """
        if not instance.raw_authors:
            return []

        try:
            raw_authors_data = instance.raw_authors

            # Handle JSON string input
            if isinstance(raw_authors_data, str):
                try:
                    raw_authors_data = json.loads(raw_authors_data)
                except (json.JSONDecodeError, TypeError):
                    logger.debug(
                        f"Failed to parse raw_authors as JSON string "
                        f"for paper {instance.id}"
                    )
                    return []

            # Ensure it's a list
            if not isinstance(raw_authors_data, list):
                return []

            # Handle list of JSON strings
            parsed_authors = []
            for item in raw_authors_data:
                if isinstance(item, str):
                    try:
                        parsed_item = json.loads(item)
                        if isinstance(parsed_item, dict):
                            parsed_authors.append(parsed_item)
                    except (json.JSONDecodeError, TypeError):
                        continue
                elif isinstance(item, dict):
                    # Make a deep copy to avoid mutating the original
                    parsed_authors.append(json.loads(json.dumps(item)))
                else:
                    continue

            if not parsed_authors:
                return []

            # Check if data needs transformation (has raw format keys)
            needs_transformation = any(
                isinstance(author, dict)
                and (
                    "family" in author
                    or "literal" in author
                    or "author" in author
                    or ("name" in author and "first_name" not in author)
                )
                for author in parsed_authors
            )

            # Transform if needed using format_raw_authors
            if needs_transformation:
                try:
                    formatted_authors = format_raw_authors(parsed_authors)
                except Exception as e:
                    logger.debug(
                        f"format_raw_authors failed for paper {instance.id}: {e}"
                    )
                    # Fall back to direct extraction
                    formatted_authors = parsed_authors
            else:
                formatted_authors = parsed_authors

            # Extract author names, handling both formatted and raw formats
            result = []
            for author in formatted_authors:
                if not isinstance(author, dict):
                    continue

                # Try formatted format first
                first_name = author.get("first_name")
                last_name = author.get("last_name")
                # Fall back to raw formats if needed
                if not first_name:
                    first_name = author.get("given", "")
                if not last_name:
                    last_name = author.get("family", "")

                # Try literal format
                if not first_name and not last_name and "literal" in author:
                    name = author.get("literal", "")
                    if name:
                        names = name.split(" ")
                        first_name = names[0] if names else ""
                        last_name = names[-1] if len(names) > 1 else ""

                # Try name field
                if not first_name and not last_name and "name" in author:
                    name = author.get("name", "")
                    if name:
                        names = name.split(" ")
                        first_name = names[0] if names else ""
                        last_name = names[-1] if len(names) > 1 else ""
                if first_name or last_name:
                    result.append(
                        {
                            "first_name": first_name or "",
                            "last_name": last_name or "",
                        }
                    )

            return result

        except Exception as e:
            logger.debug(
                f"Failed to prepare authors for suggestions "
                f"for paper {instance.id}: {e}"
            )
            return []

    def prepare_doi_indexing(self, instance) -> str:
        return instance.doi or ""

    def get_hub_names(self, instance) -> list[str]:
        """
        Return flat list of hub names for indexing.
        """
        return [hub.name for hub in instance.hubs.all()]

    def prepare_hubs(self, instance) -> list[dict[str, Any]]:
        """Prepare hubs data for indexing with namespace."""
        if not instance.unified_document:
            return []

        try:
            hubs_queryset = instance.unified_document.hubs.all()
            if not hubs_queryset.exists():
                return []

            result = []
            for hub in hubs_queryset:
                result.append(
                    {
                        "id": hub.id,
                        "name": hub.name if hub.name else None,
                        "slug": hub.slug if hub.slug else "",
                        "namespace": hub.namespace if hub.namespace else None,
                    }
                )
            return result
        except Exception as e:
            logger.warning(f"Failed to prepare hubs for paper {instance.id}: {e}")
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

    def _get_journal_name_from_hubs(self, instance) -> str | None:
        """Extract journal name from hubs where namespace='journal'."""
        if not instance.unified_document:
            return None

        try:
            hubs = instance.unified_document.hubs.filter(namespace="journal")
            journal_hub = hubs.first()
            if journal_hub and journal_hub.name:
                return journal_hub.name
        except Exception as e:
            logger.warning(
                f"Failed to get journal name from hubs for paper {instance.id}: {e}"
            )

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
