import logging
from typing import List, Optional

from django.core.cache import cache
from django.db.models import Case, IntegerField, QuerySet, When

from feed.feed_config import PERSONALIZE_CONFIG
from feed.models import FeedEntry

logger = logging.getLogger(__name__)


class PersonalizeFeedService:
    def __init__(self):
        from feed.clients.personalize_client import PersonalizeClient

        self.personalize_client = PersonalizeClient()
        self.cache_hit = False

    def get_feed_queryset(
        self,
        user_id: Optional[int] = None,
        filter_param: Optional[str] = None,
        num_results: Optional[int] = None,
        force_refresh: bool = False,
    ) -> QuerySet:
        if not user_id:
            return FeedEntry.objects.none()

        # Apply default filter if none specified
        if not filter_param:
            filter_param = PERSONALIZE_CONFIG["default_filter"]

        recommended_ids = self._get_recommendation_ids(
            user_id=user_id,
            filter_param=filter_param,
            num_results=num_results,
            force_refresh=force_refresh,
        )

        if not recommended_ids:
            return FeedEntry.objects.none()

        return self._create_ordered_queryset(recommended_ids)

    def _get_recommendation_ids(
        self,
        user_id: int,
        filter_param: str,
        num_results: Optional[int],
        force_refresh: bool,
    ) -> List[int]:
        if num_results is None:
            num_results = PERSONALIZE_CONFIG.get("num_results", 200)

        cache_key = self._build_cache_key(user_id, filter_param)

        if not force_refresh:
            cached_ids = cache.get(cache_key)
            if cached_ids is not None:
                logger.debug(f"Recommendation cache hit for user {user_id}")
                self.cache_hit = True
                return cached_ids

        logger.info(f"Fetching recommendations for user {user_id}")
        self.cache_hit = False

        try:
            ids = self.personalize_client.get_recommendations_for_user(
                user_id=str(user_id),
                filter=filter_param,
                num_results=num_results,
            )

            ids = [int(id) for id in ids] if ids else []

            timeout = PERSONALIZE_CONFIG.get("cache_timeout", 1800)
            cache.set(cache_key, ids, timeout=timeout)
            logger.info(f"Cached recommendations for user {user_id}")

            return ids

        except Exception as e:
            logger.error(f"Error fetching recommendations for user {user_id}: {e}")
            return []

    def _build_cache_key(self, user_id: int, filter_param: Optional[str]) -> str:
        filter_value = filter_param if filter_param else "none"
        return f"personalized_ids:user-is-{user_id}:filter-is-{filter_value}"

    def _create_ordered_queryset(self, recommended_ids: List[int]) -> QuerySet:
        if not recommended_ids:
            return FeedEntry.objects.none()

        queryset = FeedEntry.objects.filter(unified_document_id__in=recommended_ids)

        queryset = queryset.select_related(
            "content_type",
            "user",
            "user__author_profile",
            "user__userverification",
        )

        ordering = Case(
            *[
                When(unified_document_id=pk, then=pos)
                for pos, pk in enumerate(recommended_ids)
            ],
            output_field=IntegerField(),
        )

        return queryset.order_by(ordering)

    def invalidate_cache_for_user(
        self,
        user_id: int,
        filter_param: Optional[str] = None,
    ) -> None:
        if filter_param:
            filters = [filter_param]
        else:
            default_filter = PERSONALIZE_CONFIG["default_filter"]
            filters = [default_filter, None]

        for filter_val in filters:
            cache_key = self._build_cache_key(
                user_id=user_id,
                filter_param=filter_val,
            )
            cache.delete(cache_key)
            logger.info(f"Invalidated cache: {cache_key}")
