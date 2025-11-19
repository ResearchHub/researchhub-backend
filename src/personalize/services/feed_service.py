import logging
from typing import Any, Dict, Optional

from django.core.cache import cache

from personalize.clients.recommendation_client import RecommendationClient
from personalize.config.settings import PERSONALIZE_CONFIG

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TIMEOUT = 1800


class FeedService:
    def __init__(self, personalize_client: Optional[RecommendationClient] = None):
        self.personalize_client = personalize_client or RecommendationClient()
        self.cache_hit = False

    def get_recommendation_ids(
        self,
        user_id: int,
        filter_param: Optional[str] = None,
        num_results: Optional[int] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        if not filter_param:
            filter_param = PERSONALIZE_CONFIG["default_filter"]

        return self._get_recommendation_ids(
            user_id=user_id,
            filter_param=filter_param,
            num_results=num_results,
            force_refresh=force_refresh,
        )

    def _get_recommendation_ids(
        self,
        user_id: int,
        filter_param: str,
        num_results: Optional[int],
        force_refresh: bool,
    ) -> Dict[str, Any]:
        if num_results is None:
            num_results = PERSONALIZE_CONFIG.get("num_results", 200)

        cache_key = self._build_cache_key(user_id, filter_param)

        if not force_refresh:
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.debug(f"Recommendation cache hit for user {user_id}")
                self.cache_hit = True
                return cached_result

        logger.info(f"Fetching recommendations for user {user_id}")
        self.cache_hit = False

        result = self.personalize_client.get_recommendations_for_user(
            user_id=str(user_id),
            filter=filter_param,
            num_results=num_results,
        )

        timeout = PERSONALIZE_CONFIG.get("cache_timeout", DEFAULT_CACHE_TIMEOUT)
        cache.set(cache_key, result, timeout=timeout)
        logger.info(f"Cached recommendations for user {user_id}")

        return result

    def _build_cache_key(self, user_id: int, filter_param: Optional[str]) -> str:
        filter_value = filter_param if filter_param else "none"
        return f"personalized_ids:user-is-{user_id}:filter-is-{filter_value}"

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
