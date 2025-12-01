"""
Service for enriching Elasticsearch search results with database data.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.db import connection

from feed.serializers import (
    PaperSerializer,
    PostSerializer,
    SimpleAuthorSerializer,
    serialize_feed_metrics,
)
from paper.models import Paper
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from search.services.search_result_validator import SearchResultValidator
from user.models import User

logger = logging.getLogger(__name__)


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

        papers, posts = self._fetch_documents_parallel(paper_ids, post_ids)

        paper_lookup = {paper.id: paper for paper in papers}
        post_lookup = {post.id: post for post in posts}

        if len(es_results) > 5:
            enriched_results = self._enrich_results_parallel(
                es_results, paper_lookup, post_lookup
            )
        else:
            enriched_results = self._enrich_results_sequential(
                es_results, paper_lookup, post_lookup
            )

        return enriched_results

    def _fetch_documents_parallel(
        self, paper_ids: list[int], post_ids: list[int]
    ) -> tuple[list[Paper], list[ResearchhubPost]]:
        papers = []
        posts = []

        if paper_ids and post_ids:

            def fetch_papers_with_cleanup():
                try:
                    return self._fetch_papers(paper_ids)
                finally:
                    connection.close()

            def fetch_posts_with_cleanup():
                try:
                    return self._fetch_posts(post_ids)
                finally:
                    connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                paper_future = executor.submit(fetch_papers_with_cleanup)
                post_future = executor.submit(fetch_posts_with_cleanup)

                papers = paper_future.result()
                posts = post_future.result()
        else:
            if paper_ids:
                papers = self._fetch_papers(paper_ids)
            if post_ids:
                posts = self._fetch_posts(post_ids)

        return papers, posts

    def _enrich_results_parallel(
        self,
        es_results: list[dict[str, Any]],
        paper_lookup: dict[int, Paper],
        post_lookup: dict[int, ResearchhubPost],
    ) -> list[dict[str, Any]]:
        enriched_results = [None] * len(es_results)

        def enrich_single_result(
            index: int, result: dict[str, Any]
        ) -> tuple[int, dict[str, Any]]:
            try:
                doc_id = result.get("id")
                doc_type = result.get("type")

                if doc_type == "paper" and doc_id in paper_lookup:
                    enriched_result = self._enrich_paper_result(
                        result, paper_lookup[doc_id]
                    )
                    return index, enriched_result
                elif doc_type == "post" and doc_id in post_lookup:
                    enriched_result = self._enrich_post_result(
                        result, post_lookup[doc_id]
                    )
                    return index, enriched_result
                else:
                    logger.warning(
                        f"Document {doc_id} ({doc_type}) not found in database"
                    )
                    return index, result
            except Exception as e:
                logger.error(
                    f"Error enriching result at index {index}: {str(e)}", exc_info=True
                )
                return index, result
            finally:
                connection.close()

        max_workers = min(len(es_results), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(enrich_single_result, i, result): i
                for i, result in enumerate(es_results)
            }

            for future in as_completed(futures):
                try:
                    index, enriched_result = future.result()
                    enriched_results[index] = enriched_result
                except Exception as e:
                    index = futures[future]
                    logger.error(
                        f"Unexpected error in future for index {index}: {str(e)}",
                        exc_info=True,
                    )
                    enriched_results[index] = es_results[index]

        return enriched_results

    def _enrich_results_sequential(
        self,
        es_results: list[dict[str, Any]],
        paper_lookup: dict[int, Paper],
        post_lookup: dict[int, ResearchhubPost],
    ) -> list[dict[str, Any]]:
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
        return {
            "type": es_result.get("type"),
            "snippet": es_result.get("snippet"),
            "matched_field": es_result.get("matched_field"),
            "_search_score": es_result.get("_search_score"),
            "score": es_result.get("score"),
        }

    def _get_author(self, user: User | None) -> dict[str, Any] | None:
        if not user or not hasattr(user, "author_profile"):
            return None

        try:
            return SimpleAuthorSerializer(user.author_profile).data
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            user_id = getattr(user, "id", "unknown")
            logger.debug(f"Failed to serialize author for user {user_id}: {e}")
            return None

    def _get_hot_score_v2(
        self, unified_document: ResearchhubUnifiedDocument | None
    ) -> int:
        if not unified_document:
            return 0
        return getattr(unified_document, "hot_score_v2", 0)

    def _build_minimal_enrichment(
        self,
        es_result: dict[str, Any],
        unified_document: ResearchhubUnifiedDocument | None,
    ) -> dict[str, Any]:
        return {
            **es_result,
            "id": es_result.get("id"),
            "type": es_result.get("type"),
            "title": es_result.get("title", ""),
            "metrics": {},
            "action": "PUBLISH",
            "hot_score_v2": self._get_hot_score_v2(unified_document),
        }

    def _serialize_with_fallback(
        self,
        serializer_class: type[PaperSerializer | PostSerializer],
        obj: Paper | ResearchhubPost,
        obj_name: str,
        obj_id: int,
    ) -> dict[str, Any] | None:
        try:
            return serializer_class(obj).data
        except (ValueError, TypeError) as ser_error:
            logger.warning(
                f"{serializer_class.__name__} failed for {obj_name} {obj_id}: "
                f"{str(ser_error)}. Using minimal data."
            )
            return None

    def _ensure_required_fields(
        self, result: dict[str, Any], es_result: dict[str, Any], doc_type: str
    ) -> dict[str, Any]:
        result_id = result.get("id") or es_result.get("id")
        if result_id is not None:
            try:
                result["id"] = int(result_id)
            except (ValueError, TypeError):
                try:
                    result["id"] = int(es_result.get("id", 0))
                except (ValueError, TypeError):
                    result["id"] = 0

        result["type"] = result.get("type") or es_result.get("type") or doc_type
        result["title"] = result.get("title") or es_result.get("title") or ""

        return result

    def _clean_nested_fields(self, result: dict[str, Any]) -> dict[str, Any]:
        self._clean_list_fields(result)
        self._clean_dict_fields(result)
        self._clean_metrics_field(result)
        self._clean_external_metadata_field(result)
        return result

    def _clean_list_fields(self, result: dict[str, Any]) -> None:
        list_fields = ["reviews", "bounties", "purchases", "hubs", "authors"]
        for field in list_fields:
            if field in result and result[field] is None:
                result[field] = []

    def _clean_dict_fields(self, result: dict[str, Any]) -> None:
        dict_fields = [
            "hub",
            "category",
            "subcategory",
            "author",
            "journal",
            "fundraise",
            "grant",
        ]
        for field in dict_fields:
            if field not in result:
                continue

            value = result[field]
            if value == "":
                result[field] = None
            elif not isinstance(value, dict):
                result[field] = None
            elif field == "grant":
                result[field] = SearchResultValidator.validate_grant_dict(value)
            elif field == "fundraise":
                result[field] = SearchResultValidator.validate_fundraise_dict(value)

    def _clean_metrics_field(self, result: dict[str, Any]) -> None:
        if "metrics" not in result:
            return
        if result["metrics"] is None or not isinstance(result["metrics"], dict):
            result["metrics"] = {}

    def _clean_external_metadata_field(self, result: dict[str, Any]) -> None:
        if "external_metadata" not in result:
            return
        value = result["external_metadata"]
        if value == "" or (value is not None and not isinstance(value, dict)):
            result["external_metadata"] = None

    def _clean_nested_serializer_fields(self, result: dict[str, Any]) -> dict[str, Any]:
        for field in ["hub", "category", "subcategory"]:
            if field in result:
                result[field] = SearchResultValidator.validate_hub_dict(result[field])

        if "journal" in result:
            result["journal"] = SearchResultValidator.validate_journal_dict(
                result["journal"]
            )

        if "author" in result:
            result["author"] = SearchResultValidator.validate_author_detail_dict(
                result["author"]
            )

        SearchResultValidator.validate_list_field(
            result, "reviews", SearchResultValidator.validate_review_dict
        )
        SearchResultValidator.validate_list_field(
            result, "bounties", SearchResultValidator.validate_bounty_dict
        )
        SearchResultValidator.validate_list_field(
            result, "purchases", SearchResultValidator.validate_purchase_dict
        )
        SearchResultValidator.validate_list_field(
            result, "hubs", SearchResultValidator.validate_hub_dict
        )
        SearchResultValidator.validate_list_field(
            result, "authors", SearchResultValidator.validate_author_dict
        )

        return result

    def _enrich_paper_result(
        self, es_result: dict[str, Any], paper: Paper
    ) -> dict[str, Any]:
        try:
            paper_data = self._serialize_with_fallback(
                PaperSerializer, paper, "paper", paper.id
            )
            if paper_data is None:
                minimal = self._build_minimal_enrichment(
                    es_result, paper.unified_document
                )
                return self._ensure_required_fields(minimal, es_result, "paper")

            metrics = serialize_feed_metrics(paper, self.paper_content_type)
            author = self._get_author(paper.uploaded_by)
            action_date = paper.paper_publish_date or paper.created_date
            hot_score_v2 = self._get_hot_score_v2(paper.unified_document)
            es_specific_fields = self._extract_es_specific_fields(es_result)

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

            if "abstract" not in enriched_result:
                enriched_result["abstract"] = getattr(paper, "abstract", None)

            enriched_result = self._ensure_required_fields(
                enriched_result, es_result, "paper"
            )
            enriched_result = self._clean_nested_fields(enriched_result)
            enriched_result = self._clean_nested_serializer_fields(enriched_result)

            return enriched_result
        except Exception as e:
            logger.error(f"Error enriching paper {paper.id}: {str(e)}", exc_info=True)
            return self._ensure_required_fields(es_result.copy(), es_result, "paper")

    def _enrich_post_result(
        self, es_result: dict[str, Any], post: ResearchhubPost
    ) -> dict[str, Any]:
        try:
            post_data = self._serialize_with_fallback(
                PostSerializer, post, "post", post.id
            )
            if post_data is None:
                minimal = self._build_minimal_enrichment(
                    es_result, post.unified_document
                )
                return self._ensure_required_fields(minimal, es_result, "post")

            metrics = serialize_feed_metrics(post, self.post_content_type)
            author = self._get_author(post.created_by)
            action_date = post.created_date
            hot_score_v2 = self._get_hot_score_v2(post.unified_document)
            es_specific_fields = self._extract_es_specific_fields(es_result)

            image_url = None
            if post.image:
                image_url = default_storage.url(post.image)

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

            if "renderable_text" not in enriched_result:
                renderable_text = getattr(post, "renderable_text", None)
                if renderable_text:
                    text = renderable_text[:255]
                    if len(renderable_text) > 255:
                        text += "..."
                    enriched_result["renderable_text"] = text

            enriched_result = self._ensure_required_fields(
                enriched_result, es_result, "post"
            )
            enriched_result = self._clean_nested_fields(enriched_result)
            enriched_result = self._clean_nested_serializer_fields(enriched_result)

            return enriched_result
        except Exception as e:
            logger.error(f"Error enriching post {post.id}: {str(e)}", exc_info=True)
            return self._ensure_required_fields(es_result.copy(), es_result, "post")
