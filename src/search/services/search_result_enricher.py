"""
Service for enriching Elasticsearch search results with database data.
"""

import logging
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage

from feed.serializers import (
    PaperSerializer,
    PostSerializer,
    SimpleAuthorSerializer,
    serialize_feed_metrics,
)
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

logger = logging.getLogger(__name__)


# Enriches Elasticsearch search results with database data.
class SearchResultEnricher:

    def __init__(self):
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

    def enrich_results(self, es_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not es_results:
            return []

        paper_ids = []
        post_ids = []

        for result in es_results:
            doc_id = result.get("id")
            doc_type = result.get("type")

            if doc_type == "paper":
                paper_ids.append(doc_id)
            elif doc_type == "post":
                post_ids.append(doc_id)

        papers = self._fetch_papers(paper_ids) if paper_ids else []
        posts = self._fetch_posts(post_ids) if post_ids else []

        paper_lookup = {paper.id: paper for paper in papers}
        post_lookup = {post.id: post for post in posts}

        # Enrich each result
        enriched_results = []
        for result in es_results:
            doc_id = result.get("id")
            doc_type = result.get("type")

            if doc_type == "paper" and doc_id in paper_lookup:
                enriched_result = self._enrich_paper_result(
                    result, paper_lookup[doc_id]
                )
                enriched_results.append(enriched_result)
            elif doc_type == "post" and doc_id in post_lookup:
                enriched_result = self._enrich_post_result(result, post_lookup[doc_id])
                enriched_results.append(enriched_result)
            else:
                logger.warning(f"Document {doc_id} ({doc_type}) not found in database")
                enriched_results.append(result)

        return enriched_results

    def _fetch_papers(self, paper_ids: list[int]) -> list[Paper]:
        return (
            Paper.objects.filter(id__in=paper_ids, is_removed=False)
            .select_related(
                "unified_document", "uploaded_by", "uploaded_by__author_profile"
            )
            .prefetch_related(
                "unified_document__hubs",
                "unified_document__related_bounties",
                "unified_document__reviews",
                "unified_document__reviews__created_by",
                "unified_document__reviews__created_by__author_profile",
                "purchases",
                "purchases__user",
                "purchases__user__author_profile",
            )
            .all()
        )

    def _fetch_posts(self, post_ids: list[int]) -> list[ResearchhubPost]:
        return (
            ResearchhubPost.objects.filter(id__in=post_ids, is_removed=False)
            .select_related(
                "unified_document",
                "created_by",
                "created_by__author_profile",
            )
            .prefetch_related(
                "unified_document__hubs",
                "unified_document__related_bounties",
                "unified_document__reviews",
                "unified_document__reviews__created_by",
                "unified_document__reviews__created_by__author_profile",
                "unified_document__fundraises",
                "unified_document__fundraises__created_by",
                "unified_document__fundraises__created_by__author_profile",
                "unified_document__fundraises__contributors",
                "unified_document__fundraises__contributors__author_profile",
                "unified_document__grants",
                "unified_document__grants__created_by",
                "unified_document__grants__created_by__author_profile",
                "unified_document__grants__contacts",
                "unified_document__grants__contacts__author_profile",
                "purchases",
                "purchases__user",
                "purchases__user__author_profile",
            )
            .all()
        )

    def _extract_es_specific_fields(self, es_result: dict[str, Any]) -> dict[str, Any]:
        """Extract ES-specific fields that should be preserved."""
        return {
            "type": es_result.get("type"),
            "snippet": es_result.get("snippet"),
            "matched_field": es_result.get("matched_field"),
            "_search_score": es_result.get("_search_score"),
            "score": es_result.get("score"),
        }

    def _get_author(self, user) -> dict[str, Any] | None:
        if not user or not hasattr(user, "author_profile"):
            return None

        try:
            return SimpleAuthorSerializer(user.author_profile).data
        except Exception:
            logger.debug(f"Failed to serialize author for user {user.id}")
            return None

    def _get_hot_score_v2(self, unified_document) -> int:
        if not unified_document:
            return 0
        return getattr(unified_document, "hot_score_v2", 0)

    def _build_minimal_enrichment(
        self, es_result: dict[str, Any], unified_document
    ) -> dict[str, Any]:
        """Build minimal enrichment dict when full serialization fails."""
        return {
            **es_result,
            "metrics": {},
            "action": "PUBLISH",
            "hot_score_v2": self._get_hot_score_v2(unified_document),
        }

    def _serialize_with_fallback(
        self, serializer_class, obj, obj_name: str, obj_id: int
    ) -> dict[str, Any] | None:
        try:
            return serializer_class(obj).data
        except (ValueError, TypeError) as ser_error:
            logger.warning(
                f"{serializer_class.__name__} failed for {obj_name} {obj_id}: "
                f"{str(ser_error)}. Using minimal data."
            )
            return None

    def _enrich_paper_result(
        self, es_result: dict[str, Any], paper: Paper
    ) -> dict[str, Any]:
        """Enrich a paper search result with database data."""
        try:
            # Try to serialize paper data
            paper_data = self._serialize_with_fallback(
                PaperSerializer, paper, "paper", paper.id
            )
            if paper_data is None:
                return self._build_minimal_enrichment(es_result, paper.unified_document)

            # Get common enrichment data
            metrics = serialize_feed_metrics(paper, self.paper_content_type)
            author = self._get_author(paper.uploaded_by)
            action_date = paper.paper_publish_date or paper.created_date
            hot_score_v2 = self._get_hot_score_v2(paper.unified_document)
            es_specific_fields = self._extract_es_specific_fields(es_result)

            # Build enriched result
            enriched_result = {
                **paper_data,
                **es_specific_fields,
                "metrics": metrics,
                "author": author,
                "action_date": action_date,
                "action": "PUBLISH",
                "hot_score_v2": hot_score_v2,
                "external_metadata": getattr(paper, "external_metadata", None),
            }

            # Ensure abstract is included
            if "abstract" not in enriched_result:
                enriched_result["abstract"] = getattr(paper, "abstract", None)

            return enriched_result
        except Exception as e:
            logger.error(f"Error enriching paper {paper.id}: {str(e)}", exc_info=True)
            return es_result

    def _enrich_post_result(
        self, es_result: dict[str, Any], post: ResearchhubPost
    ) -> dict[str, Any]:
        try:
            # Try to serialize post data
            post_data = self._serialize_with_fallback(
                PostSerializer, post, "post", post.id
            )
            if post_data is None:
                return self._build_minimal_enrichment(es_result, post.unified_document)

            # Get common enrichment data
            metrics = serialize_feed_metrics(post, self.post_content_type)
            author = self._get_author(post.created_by)
            action_date = post.created_date
            hot_score_v2 = self._get_hot_score_v2(post.unified_document)
            es_specific_fields = self._extract_es_specific_fields(es_result)

            # Get post-specific fields
            image_url = None
            if post.image:
                image_url = default_storage.url(post.image)

            # Build enriched result
            enriched_result = {
                **post_data,
                **es_specific_fields,
                "metrics": metrics,
                "author": author,
                "action_date": action_date,
                "action": "PUBLISH",
                "hot_score_v2": hot_score_v2,
                "image_url": image_url,
            }

            # Ensure renderable_text is included
            if "renderable_text" not in enriched_result:
                renderable_text = getattr(post, "renderable_text", None)
                if renderable_text:
                    text = renderable_text[:255]
                    if len(renderable_text) > 255:
                        text += "..."
                    enriched_result["renderable_text"] = text

            return enriched_result
        except Exception as e:
            logger.error(f"Error enriching post {post.id}: {str(e)}", exc_info=True)
            return es_result
