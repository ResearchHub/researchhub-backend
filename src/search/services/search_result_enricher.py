"""
Service for enriching Elasticsearch search results with database data.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

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

        # Fetch papers and posts in parallel (always beneficial if both exist)
        papers, posts = self._fetch_documents_parallel(paper_ids, post_ids)

        paper_lookup = {paper.id: paper for paper in papers}
        post_lookup = {post.id: post for post in posts}

        # Use parallel enrichment for larger result sets (overhead not worth it for small sets)
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
        """Fetch papers and posts from database in parallel."""
        papers = []
        posts = []

        # Only use parallel fetching if we have both types, otherwise sequential is fine
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
            # Sequential fetching when only one type exists
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
        """Enrich search results in parallel."""
        enriched_results = [None] * len(es_results)

        def enrich_single_result(index: int, result: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            """Enrich a single result and return its index and enriched data."""
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
                # Close thread-local database connection (Django pattern)
                connection.close()

        # Use ThreadPoolExecutor for parallel enrichment
        # Limit workers to balance performance and resource usage
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
        """Enrich search results sequentially (for small result sets)."""
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

    def _get_author(self, user: User | None) -> dict[str, Any] | None:
        """Extract author data from user if available."""
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
        """Ensure required fields (id, type, title) are present and correct type."""
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
        """Clean nested fields to ensure they match serializer expectations."""
        list_fields = ["reviews", "bounties", "purchases", "hubs", "authors"]
        for field in list_fields:
            if field in result and result[field] is None:
                result[field] = []

        dict_fields = ["hub", "category", "subcategory", "author", "journal", "fundraise", "grant"]
        for field in dict_fields:
            if field in result:
                if result[field] == "":
                    result[field] = None
                elif not isinstance(result[field], dict) and result[field] is not None:
                    # Ensure dict fields are dicts or None
                    result[field] = None
                elif field == "grant" and isinstance(result[field], dict):
                    # Validate nested grant structure
                    result[field] = self._validate_grant_dict(result[field])
                elif field == "fundraise" and isinstance(result[field], dict):
                    # Validate nested fundraise structure
                    result[field] = self._validate_fundraise_dict(result[field])

        if "metrics" in result:
            if result["metrics"] is None:
                result["metrics"] = {}
            elif not isinstance(result["metrics"], dict):
                result["metrics"] = {}

        if "external_metadata" in result:
            if result["external_metadata"] == "":
                result["external_metadata"] = None
            elif result["external_metadata"] is not None and not isinstance(result["external_metadata"], dict):
                result["external_metadata"] = None

        return result

    def _validate_grant_dict(self, grant: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and clean grant dict to ensure nested structures are valid."""
        if not grant or not isinstance(grant, dict):
            return None

        # Validate amount field - should be dict with usd, rsc, formatted
        if "amount" in grant:
            amount = grant["amount"]
            if amount is not None and not isinstance(amount, dict):
                grant["amount"] = None

        # Validate created_by - should be dict or None
        if "created_by" in grant:
            created_by = grant["created_by"]
            if created_by is not None and not isinstance(created_by, dict):
                grant["created_by"] = None
            elif isinstance(created_by, dict) and "author_profile" in created_by:
                # Ensure author_profile is dict or None
                author_profile = created_by["author_profile"]
                if author_profile is not None and not isinstance(author_profile, dict):
                    created_by["author_profile"] = None

        # Validate contacts - should be list of dicts
        if "contacts" in grant:
            contacts = grant["contacts"]
            if contacts is None:
                grant["contacts"] = []
            elif isinstance(contacts, list):
                cleaned_contacts = []
                for contact in contacts:
                    if isinstance(contact, dict):
                        # Ensure author_profile is dict or None
                        if "author_profile" in contact:
                            author_profile = contact["author_profile"]
                            if author_profile is not None and not isinstance(author_profile, dict):
                                contact = {**contact, "author_profile": None}
                        cleaned_contacts.append(contact)
                grant["contacts"] = cleaned_contacts
            else:
                grant["contacts"] = []

        # Validate applications - should be list of dicts
        if "applications" in grant:
            applications = grant["applications"]
            if applications is None:
                grant["applications"] = []
            elif isinstance(applications, list):
                cleaned_applications = []
                for application in applications:
                    if isinstance(application, dict):
                        # Ensure applicant is dict or None
                        if "applicant" in application:
                            applicant = application["applicant"]
                            if applicant is not None and not isinstance(applicant, dict):
                                application = {**application, "applicant": None}
                            elif isinstance(applicant, dict):
                                # Ensure applicant has valid structure (id, first_name, etc.)
                                if "id" not in applicant:
                                    application = {**application, "applicant": None}
                        cleaned_applications.append(application)
                grant["applications"] = cleaned_applications
            else:
                grant["applications"] = []

        return grant

    def _validate_fundraise_dict(self, fundraise: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and clean fundraise dict to ensure nested structures are valid."""
        if not fundraise or not isinstance(fundraise, dict):
            return None

        # Validate amount_raised - should be dict with usd, rsc
        if "amount_raised" in fundraise:
            amount_raised = fundraise["amount_raised"]
            if amount_raised is not None and not isinstance(amount_raised, dict):
                fundraise["amount_raised"] = None

        # Validate goal_amount - should be dict with usd, rsc
        if "goal_amount" in fundraise:
            goal_amount = fundraise["goal_amount"]
            if goal_amount is not None and not isinstance(goal_amount, dict):
                fundraise["goal_amount"] = None

        # Validate created_by - should be dict or None
        if "created_by" in fundraise:
            created_by = fundraise["created_by"]
            if created_by is not None and not isinstance(created_by, dict):
                fundraise["created_by"] = None
            elif isinstance(created_by, dict) and "author_profile" in created_by:
                # Ensure author_profile is dict or None
                author_profile = created_by["author_profile"]
                if author_profile is not None and not isinstance(author_profile, dict):
                    created_by["author_profile"] = None

        # Validate contributors - should be dict with total and top (array)
        if "contributors" in fundraise:
            contributors = fundraise["contributors"]
            if contributors is None:
                fundraise["contributors"] = {"total": 0, "top": []}
            elif isinstance(contributors, dict):
                # Ensure total is int
                if "total" in contributors:
                    try:
                        contributors["total"] = int(contributors["total"])
                    except (ValueError, TypeError):
                        contributors["total"] = 0
                # Ensure top is list
                if "top" in contributors:
                    if not isinstance(contributors["top"], list):
                        contributors["top"] = []
                    else:
                        # Validate each contributor in top array
                        cleaned_top = []
                        for contributor in contributors["top"]:
                            if isinstance(contributor, dict):
                                # Ensure author_profile is dict or None
                                if "author_profile" in contributor:
                                    author_profile = contributor["author_profile"]
                                    if author_profile is not None and not isinstance(author_profile, dict):
                                        contributor = {**contributor, "author_profile": None}
                                cleaned_top.append(contributor)
                        contributors["top"] = cleaned_top
            else:
                fundraise["contributors"] = {"total": 0, "top": []}

        return fundraise

    def _validate_hub_dict(self, hub: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean hub dict to ensure required fields are present."""
        if not hub or not isinstance(hub, dict):
            return None

        hub_id = hub.get("id")
        name = hub.get("name")
        slug = hub.get("slug")

        if hub_id is None or name is None or slug is None:
            return None

        try:
            hub_id = int(hub_id)
        except (ValueError, TypeError):
            return None

        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(slug, str) or not slug.strip():
            return None

        return {"id": hub_id, "name": name.strip(), "slug": slug.strip()}

    def _validate_review_dict(self, review: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean review dict to ensure required fields are present."""
        if not review or not isinstance(review, dict):
            return None

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

        purchase_id = purchase.get("id")
        amount = purchase.get("amount")

        if purchase_id is None or amount is None:
            return None

        try:
            purchase_id = int(purchase_id)
            # DecimalField accepts string, int, float, or Decimal
            # Convert to string to ensure proper DecimalField handling
            if isinstance(amount, str):
                # Validate it's a valid number string
                float(amount)  # Will raise ValueError if invalid
                amount_str = amount
            else:
                # Convert numeric types to string for DecimalField
                amount_str = str(amount)
        except (ValueError, TypeError):
            return None

        return {"id": purchase_id, "amount": amount_str, "user": purchase.get("user")}

    def _validate_journal_dict(self, journal: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and clean journal dict to ensure required fields are present."""
        if not journal or not isinstance(journal, dict):
            return None

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

    def _validate_author_dict(self, author: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate and ensure author dict has required fields including full_name."""
        if not author or not isinstance(author, dict):
            return None

        first_name = author.get("first_name", "") or ""
        last_name = author.get("last_name", "") or ""
        full_name = author.get("full_name", "") or ""

        if not full_name and (first_name or last_name):
            full_name = f"{first_name} {last_name}".strip()

        if not full_name:
            full_name = "Unknown Author"

        return {
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
        }

    def _validate_list_field(
        self,
        result: dict[str, Any],
        field_name: str,
        validator_func: Callable[[dict[str, Any] | None], dict[str, Any] | None],
    ) -> None:
        """Validate a list field using the provided validator function."""
        if field_name in result and isinstance(result[field_name], list):
            result[field_name] = [
                validated_item
                for item in result[field_name]
                if (validated_item := validator_func(item)) is not None
            ]

    def _clean_nested_serializer_fields(self, result: dict[str, Any]) -> dict[str, Any]:
        """Clean and validate nested serializer fields to prevent KeyErrors."""
        for field in ["hub", "category", "subcategory"]:
            if field in result:
                result[field] = self._validate_hub_dict(result[field])

        if "journal" in result:
            result["journal"] = self._validate_journal_dict(result["journal"])

        if "author" in result:
            result["author"] = self._validate_author_detail_dict(result["author"])

        self._validate_list_field(result, "reviews", self._validate_review_dict)
        self._validate_list_field(result, "bounties", self._validate_bounty_dict)
        self._validate_list_field(result, "purchases", self._validate_purchase_dict)
        self._validate_list_field(result, "hubs", self._validate_hub_dict)
        self._validate_list_field(result, "authors", self._validate_author_dict)

        return result

    def _enrich_paper_result(
        self, es_result: dict[str, Any], paper: Paper
    ) -> dict[str, Any]:
        """Enrich a paper search result with database data."""
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
        """Enrich a post search result with database data."""
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
