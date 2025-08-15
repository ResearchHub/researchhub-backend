import logging

from django_opensearch_dsl import fields as es_fields
from django_opensearch_dsl.registries import registry

from paper.models import Paper
from paper.utils import pdf_copyright_allows_display
from search.analyzers import content_analyzer, title_analyzer

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
        queryset_pagination = 25  # Drastically reduced to avoid memory issues
        fields = ["id"]
        # Use iterator to reduce memory when processing large datasets
        ignore_signals = False  # Keep signals for real-time updates

    def get_queryset(self, filter_=None, exclude=None, count=None):
        """
        Override to optimize the queryset for indexing by deferring large fields.
        This is called by django-opensearch-dsl's get_indexing_queryset.
        """
        qs = (
            Paper.objects.all()
            # Removed select_related and prefetch_related due to data integrity issues
            # This will cause more queries but avoids the ValueError
            .defer(
                # Defer large JSON and file fields that aren't used in indexing
                "csl_item",  # Large JSON field not used
                "external_metadata",  # Large JSON field not used
                "pdf_file_extract",  # File field not used
                "edited_file_extract",  # File field not used
                "abstract_src",  # File field not used
                "file",  # PDF file not used
                # Keep open_alex_raw_json as it's used for keywords
                # Keep abstract as it's indexed
                # Keep raw_authors as it's used for author names
            )
        )
        
        if filter_:
            qs = qs.filter(filter_)
        if exclude:
            qs = qs.exclude(exclude)
        if count:
            qs = qs[:count]
            
        return qs
    
    def get_indexing_queryset(self, verbose=False, filter_=None, exclude=None, 
                            count=None, action="index", stdout=None):
        """
        Override to use Django's iterator for memory-efficient processing.
        This method yields objects one at a time using iterator() instead of
        loading entire chunks into memory via slicing.
        """
        import sys
        import time
        
        if stdout is None:
            stdout = sys.stdout
            
        # Get the optimized queryset using our get_queryset method
        # (filters, excludes, and count are already applied there)
        qs = self.get_queryset(filter_=filter_, exclude=exclude, count=count)
        
        # Order by pk for consistent iteration
        qs = qs.order_by("pk")
            
        # Get total count for progress reporting
        total = qs.count() if verbose else 0
        processed = 0
        start_time = time.time()
        
        # Use iterator with a small chunk size for memory efficiency
        # This loads objects from the database in chunks but yields them one at a time
        for obj in qs.iterator(chunk_size=100):
            # Only yield objects that should be indexed
            if self.should_index_object(obj):
                processed += 1
                
                # Show progress if verbose
                if verbose and processed % 100 == 0:
                    pct = round(processed / total * 100) if total > 0 else 0
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (total - processed) / rate if rate > 0 else 0
                    eta_str = f"{int(eta // 60)} mins" if eta > 60 else f"{int(eta)} secs"
                    stdout.write(
                        f"Indexing Paper: {pct}% ({eta_str} remaining, "
                        f"{rate:.1f} papers/sec)\r"
                    )
                    stdout.flush()
                    
                yield obj
                
        if verbose:
            stdout.write(f"Indexed {processed} Papers: OK          \n")
            stdout.flush()
    
    def should_index_object(self, obj):
        return not obj.is_removed

    # Used specifically for "autocomplete" style suggest feature.
    # Includes a bunch of phrases the user may search by.
    def prepare_suggestion_phrases(self, instance):
        """
        Optimized version that reduces memory usage by:
        1. Early returns for empty data
        2. Limited string operations
        3. Defensive handling of large datasets
        """
        phrases = []

        # Just add basic phrases for autocomplete
        phrases.append(str(instance.id))

        # Title
        if instance.title:
            phrases.append(instance.title[:200])  # Limit title length

        # DOI
        if instance.doi:
            phrases.append(instance.doi)

        # Authors - very limited
        try:
            if instance.raw_authors and len(instance.raw_authors) > 0:
                # Only process first 5 authors
                for author in instance.raw_authors[:5]:
                    if isinstance(author, dict):
                        first = author.get("first_name", "")
                        last = author.get("last_name", "")
                        if first and last:
                            phrases.append(f"{first} {last}")
        except Exception:
            pass  # Silently skip errors

        # Weight
        weight = 1
        try:
            if instance.unified_document and instance.unified_document.hot_score > 0:
                weight = min(100, max(1, instance.unified_document.hot_score // 10))
        except Exception:
            pass

        # Deduplicate and limit
        deduped = list(set(p for p in phrases if p))[:20]  # Max 20 phrases

        return {
            "input": deduped,
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
        Optimized to limit memory usage.
        """
        authors = []
        try:
            # Limit to 20 authors to prevent memory issues
            for authorship in instance.authorships.all()[:20]:
                authors.append(
                    {
                        "author_id": authorship.author.id,
                        "author_position": authorship.author_position,
                        "full_name": authorship.raw_author_name or "",
                    }
                )
        except Exception:
            pass  # Silently skip if there are issues
        return authors
