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
            "id": es_result.get("id"),
            "type": es_result.get("type"),
            "title": es_result.get("title", ""),
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

    def _ensure_required_fields(
        self, result: dict[str, Any], es_result: dict[str, Any], doc_type: str
    ) -> dict[str, Any]:
        """Ensure required fields (id, type, title) are present and correct type."""
        # Ensure id is an integer (ES returns string, serializer expects int)
        result_id = result.get("id") or es_result.get("id")
        if result_id is not None:
            try:
                result["id"] = int(result_id)
            except (ValueError, TypeError):
                # Fallback: try to get from es_result or use 0
                try:
                    result["id"] = int(es_result.get("id", 0))
                except (ValueError, TypeError):
                    result["id"] = 0

        # Ensure type is present
        result["type"] = result.get("type") or es_result.get("type") or doc_type

        # Ensure title is present (non-empty string)
        result["title"] = result.get("title") or es_result.get("title") or ""

        return result

    def _clean_nested_fields(self, result: dict[str, Any]) -> dict[str, Any]:
        """Clean nested fields to ensure they match serializer expectations."""
        # Ensure lists are lists (not None)
        list_fields = ["reviews", "bounties", "purchases", "hubs", "authors"]
        for field in list_fields:
            if field in result and result[field] is None:
                result[field] = []

        # Ensure dict fields are dicts or None (not empty strings)
        dict_fields = ["hub", "category", "subcategory", "author", "journal"]
        for field in dict_fields:
            if field in result and result[field] == "":
                result[field] = None

        return result

    def _validate_hub_dict(self, hub: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean hub dict to ensure required fields are present."""
        if not hub or not isinstance(hub, dict):
            return None

        # HubSerializer requires: id, name, slug (all required, no allow_null)
        hub_id = hub.get("id")
        name = hub.get("name")
        slug = hub.get("slug")

        # If any required field is missing or None, return None
        if hub_id is None or name is None or slug is None:
            return None

        # Ensure id is an integer
        try:
            hub_id = int(hub_id)
        except (ValueError, TypeError):
            return None

        # Ensure name and slug are non-empty strings
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(slug, str) or not slug.strip():
            return None

        return {"id": hub_id, "name": name.strip(), "slug": slug.strip()}

    def _validate_review_dict(self, review: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean review dict to ensure required fields are present."""
        if not review or not isinstance(review, dict):
            return None

        # ReviewSerializer requires: id, score (both required)
        review_id = review.get("id")
        score = review.get("score")

        if review_id is None or score is None:
            return None

        try:
            review_id = int(review_id)
            score = int(score)
        except (ValueError, TypeError):
            return None

        return {"id": review_id, "score": score, "author": review.get("author")}

    def _validate_bounty_dict(self, bounty: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean bounty dict to ensure required fields are present."""
        if not bounty or not isinstance(bounty, dict):
            return None

        # BountySerializer requires: id, status (both required)
        bounty_id = bounty.get("id")
        status = bounty.get("status")

        if bounty_id is None or status is None:
            return None

        try:
            bounty_id = int(bounty_id)
        except (ValueError, TypeError):
            return None

        if not isinstance(status, str) or not status.strip():
            return None

        return {
            "id": bounty_id,
            "status": status.strip(),
            "amount": bounty.get("amount", 0),
            "bounty_type": bounty.get("bounty_type"),
            "expiration_date": bounty.get("expiration_date"),
            "contributors": bounty.get("contributors", []),
            "contributions": bounty.get("contributions", []),
        }

    def _validate_purchase_dict(self, purchase: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean purchase dict to ensure required fields are present."""
        if not purchase or not isinstance(purchase, dict):
            return None

        # PurchaseSerializer requires: id, amount (both required)
        purchase_id = purchase.get("id")
        amount = purchase.get("amount")

        if purchase_id is None or amount is None:
            return None

        try:
            purchase_id = int(purchase_id)
            # Amount can be Decimal, float, int, or string
            if isinstance(amount, str):
                amount = float(amount)
            else:
                amount = float(amount)
        except (ValueError, TypeError):
            return None

        return {"id": purchase_id, "amount": amount, "user": purchase.get("user")}

    def _validate_journal_dict(self, journal: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean journal dict to ensure required fields are present."""
        if not journal or not isinstance(journal, dict):
            return None

        # JournalSerializer requires: id, name, slug (all required)
        journal_id = journal.get("id")
        name = journal.get("name")
        slug = journal.get("slug")

        if journal_id is None or name is None or slug is None:
            return None

        try:
            journal_id = int(journal_id)
        except (ValueError, TypeError):
            return None

        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(slug, str) or not slug.strip():
            return None

        return {
            "id": journal_id,
            "name": name.strip(),
            "slug": slug.strip(),
            "image": journal.get("image"),
            "description": journal.get("description"),
        }

    def _validate_author_detail_dict(
        self, author: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Validate and clean author detail dict to ensure required fields are present."""
        if not author or not isinstance(author, dict):
            return None

        # AuthorDetailSerializer requires: id (required)
        author_id = author.get("id")
        if author_id is None:
            return None

        try:
            author_id = int(author_id)
        except (ValueError, TypeError):
            return None

        return {
            "id": author_id,
            "first_name": author.get("first_name", ""),
            "last_name": author.get("last_name", ""),
            "profile_image": author.get("profile_image"),
            "headline": author.get("headline"),
            "user": author.get("user"),
        }

    def _clean_nested_serializer_fields(self, result: dict[str, Any]) -> dict[str, Any]:
        """Clean and validate nested serializer fields to prevent KeyErrors."""
        # Validate hub, category, subcategory (HubSerializer)
        for field in ["hub", "category", "subcategory"]:
            if field in result:
                result[field] = self._validate_hub_dict(result[field])

        # Validate journal (JournalSerializer)
        if "journal" in result:
            result["journal"] = self._validate_journal_dict(result["journal"])

        # Validate author (AuthorDetailSerializer)
        if "author" in result:
            result["author"] = self._validate_author_detail_dict(result["author"])

        # Validate lists of nested objects
        if "reviews" in result and isinstance(result["reviews"], list):
            result["reviews"] = [
                review
                for review in [
                    self._validate_review_dict(r) for r in result["reviews"]
                ]
                if review is not None
            ]

        if "bounties" in result and isinstance(result["bounties"], list):
            result["bounties"] = [
                bounty
                for bounty in [
                    self._validate_bounty_dict(b) for b in result["bounties"]
                ]
                if bounty is not None
            ]

        if "purchases" in result and isinstance(result["purchases"], list):
            result["purchases"] = [
                purchase
                for purchase in [
                    self._validate_purchase_dict(p) for p in result["purchases"]
                ]
                if purchase is not None
            ]

        if "hubs" in result and isinstance(result["hubs"], list):
            result["hubs"] = [
                hub
                for hub in [self._validate_hub_dict(h) for h in result["hubs"]]
                if hub is not None
            ]

        return result

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
                minimal = self._build_minimal_enrichment(
                    es_result, paper.unified_document
                )
                return self._ensure_required_fields(minimal, es_result, "paper")

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

            # Ensure required fields are present and correct type
            enriched_result = self._ensure_required_fields(
                enriched_result, es_result, "paper"
            )

            # Clean nested fields to match serializer expectations
            enriched_result = self._clean_nested_fields(enriched_result)

            # Validate nested serializer fields to prevent KeyErrors
            enriched_result = self._clean_nested_serializer_fields(enriched_result)

            return enriched_result
        except Exception as e:
            logger.error(f"Error enriching paper {paper.id}: {str(e)}", exc_info=True)
            # Return ES result with required fields ensured
            return self._ensure_required_fields(es_result.copy(), es_result, "paper")

    def _enrich_post_result(
        self, es_result: dict[str, Any], post: ResearchhubPost
    ) -> dict[str, Any]:
        """Enrich a post search result with database data."""
        try:
            # Try to serialize post data
            post_data = self._serialize_with_fallback(
                PostSerializer, post, "post", post.id
            )
            if post_data is None:
                minimal = self._build_minimal_enrichment(
                    es_result, post.unified_document
                )
                return self._ensure_required_fields(minimal, es_result, "post")

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

            # Ensure required fields are present and correct type
            enriched_result = self._ensure_required_fields(
                enriched_result, es_result, "post"
            )

            # Clean nested fields to match serializer expectations
            enriched_result = self._clean_nested_fields(enriched_result)

            # Validate nested serializer fields to prevent KeyErrors
            enriched_result = self._clean_nested_serializer_fields(enriched_result)

            return enriched_result
        except Exception as e:
            logger.error(f"Error enriching post {post.id}: {str(e)}", exc_info=True)
            # Return ES result with required fields ensured
            return self._ensure_required_fields(es_result.copy(), es_result, "post")
