from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone
from rest_framework.request import Request

from discussion.models import Vote
from discussion.serializers import VoteSerializer
from feed.views.common import FeedPagination
from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class FeedViewMixin:
    """
    Mixin for feed-related viewsets.
    """

    # Cache timeout
    DEFAULT_CACHE_TIMEOUT = 60 * 10  # 10 minutes

    _content_types = {}

    @property
    def _comment_content_type(self):
        return self._get_content_type(RhCommentModel)

    @property
    def _hub_content_type(self):
        return self._get_content_type(Hub)

    @property
    def _paper_content_type(self):
        return self._get_content_type(Paper)

    @property
    def _post_content_type(self):
        return self._get_content_type(ResearchhubPost)

    def _get_content_type(self, model_class):
        model_name = model_class.__name__.lower()
        if model_name not in self._content_types:
            self._content_types[model_name] = ContentType.objects.get_for_model(
                model_class
            )
        return self._content_types[model_name]

    def add_user_votes_to_response(self, user, response_data):
        """
        Add user votes to feed items in the response data.

        Args:
            user: The authenticated user
            response_data: The response data containing feed items
        """
        # Get uppercase model names from ContentType objects
        paper_type_str = self._paper_content_type.model.upper()
        post_type_str = self._post_content_type.model.upper()
        comment_type_str = self._comment_content_type.model.upper()

        paper_ids = []
        post_ids = []
        comment_ids = []

        # Collect IDs for each content type
        for item in response_data["results"]:
            content_type_str = item.get("content_type")
            if content_type_str == paper_type_str:
                paper_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == post_type_str:
                post_ids.append(int(item["content_object"]["id"]))
            elif content_type_str == comment_type_str:
                comment_ids.append(int(item["content_object"]["id"]))

        # Process paper votes
        if paper_ids:
            paper_votes = self._get_user_votes(
                user,
                paper_ids,
                self._paper_content_type,
            )

            paper_votes_map = {}
            for vote in paper_votes:
                paper_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == paper_type_str:
                    paper_id = int(item["content_object"]["id"])
                    if paper_id in paper_votes_map:
                        item["user_vote"] = paper_votes_map[paper_id]

        # Process post votes
        if post_ids:
            post_votes = self._get_user_votes(
                user,
                post_ids,
                self._post_content_type,
            )

            post_votes_map = {}
            for vote in post_votes:
                post_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == post_type_str:
                    post_id = int(item["content_object"]["id"])
                    if post_id in post_votes_map:
                        item["user_vote"] = post_votes_map[post_id]

        # Process comment votes
        if comment_ids:
            comment_votes = self._get_user_votes(
                user,
                comment_ids,
                self._comment_content_type,
            )

            comment_votes_map = {}
            for vote in comment_votes:
                comment_votes_map[int(vote.object_id)] = VoteSerializer(vote).data

            for item in response_data["results"]:
                if item.get("content_type") == comment_type_str:
                    comment_id = int(item["content_object"]["id"])
                    if comment_id in comment_votes_map:
                        item["user_vote"] = comment_votes_map[comment_id]

    def get_common_serializer_context(self):
        """
        Returns common serializer context used across feed-related viewsets.
        """
        context = {}
        context["pch_dfs_get_created_by"] = {
            "_include_fields": (
                "id",
                "author_profile",
                "first_name",
                "last_name",
            )
        }
        context["usr_dus_get_author_profile"] = {
            "_include_fields": (
                "id",
                "first_name",
                "last_name",
                "created_date",
                "updated_date",
                "profile_image",
                "is_verified",
            )
        }
        return context

    def get_cache_key(self, request: Request, feed_type: str = "") -> str:
        feed_view = request.query_params.get("feed_view", "latest")
        hub_slug = request.query_params.get("hub_slug")
        user_id = request.user.id if request.user.is_authenticated else None
        fundraise_status = request.query_params.get("fundraise_status", None)
        sort_by = request.query_params.get("sort_by", "latest")

        page = request.query_params.get("page", "1")
        page_size = request.query_params.get(
            FeedPagination.page_size_query_param,
            str(FeedPagination.page_size),
        )

        hub_part = hub_slug or "all"
        user_part = (
            "none"
            if feed_view == "popular" or feed_view == "latest"
            else f"{user_id or 'anonymous'}"
        )
        pagination_part = f"{page}-{page_size}"
        status_part = f"-{fundraise_status}" if fundraise_status else ""
        feed_type_part = f"{feed_type}_" if feed_type else ""
        sort_part = f"-{sort_by}" if sort_by != "latest" else ""

        source = request.query_params.get("source")
        source_part = f"{source}" if source else "all"

        return (
            f"{feed_type_part}feed:{feed_view}:{hub_part}:{source_part}:"
            f"{user_part}:{pagination_part}{status_part}{sort_part}"
        )

    def get_followed_hub_ids(self):
        """
        Get IDs of hubs followed by the current user.
        Returns empty list if user is not authenticated.
        """
        if not self.request.user.is_authenticated:
            return []

        return list(
            self.request.user.following.filter(
                content_type=self._hub_content_type
            ).values_list("object_id", flat=True)
        )

    def _get_user_votes(self, created_by, doc_ids, reaction_content_type):
        return Vote.objects.filter(
            content_type=reaction_content_type,
            object_id__in=doc_ids,
            created_by=created_by,
        )

    @staticmethod
    def invalidate_feed_cache_for_user(user_id):
        """
        Invalidate all feed caches for a specific user.

        This should be called when a user's feed preferences change, such as:
        - Following/unfollowing hubs
        - Following/unfollowing users
        - Any other action that affects what content appears in their feed

        Args:
            user_id: The ID of the user whose caches should be invalidated
        """
        # Cache key pattern: {feed_type}_feed:{feed_view}:{hub_part}:{source_part}:{user_part}:{pagination_part}{status_part}{sort_part}
        # For following feed, user_part is the user_id
        # We need to invalidate all possible combinations for this user

        # Django's cache doesn't support wildcard deletion out of the box
        # For now, we'll delete specific known cache keys for common pagination scenarios
        # Pages 1-4, page sizes 20 and 40
        feed_views = ["following"]
        hub_parts = ["all"]
        source_parts = ["all", "researchhub"]
        pages = ["1", "2", "3", "4"]
        page_sizes = ["20"]

        # Main feed caches (the primary personalized feed)
        # This is the only feed that has personalized "following" view
        for feed_view in feed_views:
            for hub_part in hub_parts:
                for source_part in source_parts:
                    for page in pages:
                        for page_size in page_sizes:
                            cache_key = f"feed:{feed_view}:{hub_part}:{source_part}:{user_id}:{page}-{page_size}"
                            cache.delete(cache_key)

                            # Also with hot_score sort
                            cache_key_hot = f"{cache_key}-hot_score"
                            cache.delete(cache_key_hot)

    def apply_funding_status_filtering(self, queryset, status_param):
        """Apply funding status-based filtering and sorting to a queryset."""
        if not status_param:
            return self._filter_all_funding_statuses(queryset)
        
        status_upper = status_param.upper()
        filter_methods = {
            "OPEN": self._filter_funding_open_status,
            "CLOSED": self._filter_funding_closed_status,
            "COMPLETED": self._filter_funding_completed_status,
        }
        
        filter_method = filter_methods.get(status_upper, self._filter_all_funding_statuses)
        return filter_method(queryset)
    
    def _filter_funding_open_status(self, queryset):
        """Filter for OPEN funding status with active/expired sorting."""
        return queryset.filter(
            **{self.status_field: self.model_class.OPEN}
        ).annotate(
            status=self._get_active_status_annotation()
        ).order_by("status", F(self.end_date_field).asc(nulls_last=True))
    
    def _filter_funding_closed_status(self, queryset):
        """Filter for CLOSED funding status with most recent first."""
        closed_status = getattr(self, 'closed_status', self.model_class.CLOSED)
        return queryset.filter(
            **{self.status_field: closed_status}
        ).order_by(F(self.end_date_field).desc(nulls_last=True))
    
    def _filter_funding_completed_status(self, queryset):
        """Filter for COMPLETED funding status with most recent first."""
        return queryset.filter(
            **{self.status_field: self.model_class.COMPLETED}
        ).order_by(F(self.end_date_field).desc(nulls_last=True))
    
    def _filter_all_funding_statuses(self, queryset):
        """Filter all funding statuses with priority sorting: active open, expired open, completed."""
        return queryset.annotate(
            priority_sort=self._get_priority_annotation(),
            sort_date_asc=Case(
                When(priority_sort__in=[0, 1], then=F(self.end_date_field)),
                default=None,
            ),
            sort_date_desc=Case(
                When(priority_sort=2, then=F(self.end_date_field)),
                default=None,
            )
        ).order_by(
            "priority_sort",
            F("sort_date_asc").asc(nulls_last=True),
            F("sort_date_desc").desc(nulls_last=True)
        )
    
    def _get_active_status_annotation(self):
        """Get annotation for active/expired status in OPEN items."""
        now = timezone.now()
        return Case(
            When(**{f"{self.end_date_field}__gt": now}, then=Value(0)),
            When(**{f"{self.end_date_field}__isnull": True}, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    
    def _get_priority_annotation(self):
        """Get annotation for priority sorting in ALL items."""
        now = timezone.now()
        return Case(
            When(
                **{self.status_field: self.model_class.OPEN},
                **{f"{self.end_date_field}__gt": now},
                then=Value(0)
            ),
            When(
                **{self.status_field: self.model_class.OPEN},
                **{f"{self.end_date_field}__isnull": True},
                then=Value(0)
            ),
            When(
                **{self.status_field: self.model_class.OPEN},
                **{f"{self.end_date_field}__lte": now},
                then=Value(1)
            ),
            When(
                **{self.status_field: self.model_class.COMPLETED},
                then=Value(2)
            ),
            default=Value(2),
            output_field=IntegerField(),
        )
