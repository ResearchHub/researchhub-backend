import logging

from django.contrib.admin.options import get_content_type_for_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from feed.views.feed_view_mixin import FeedViewMixin
from user.related_models.follow_model import Follow
from user.serializers import FollowSerializer
from utils.permissions import CreateOrUpdateIfAllowed

logger = logging.getLogger(__name__)


class FollowViewActionMixin:
    """
    Mixin to add follow functionality to a ViewSet.
    """

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated & CreateOrUpdateIfAllowed],
    )
    def follow(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user

        try:
            follow = create_follow(user, item)
            serializer = FollowSerializer(follow, context={"request": request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            follow = retrieve_follow(user, item)
            serializer = FollowSerializer(follow, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                f"Failed to follow: {e}", status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        detail=True,
        methods=["delete", "post"],
        permission_classes=[IsAuthenticated & CreateOrUpdateIfAllowed],
    )
    def unfollow(self, request, *args, **kwargs):
        item = self.get_object()
        user = request.user
        try:
            follow = retrieve_follow(user, item)
            serialized_data = FollowSerializer(
                follow, context={"request": request}
            ).data

            # Invalidate feed cache when unfollowing anything (hub, user, author, etc.)
            # as it affects what content appears in the user's "following" feed
            FeedViewMixin.invalidate_feed_cache_for_user(user.id)

            follow.delete()
            return Response(serialized_data, status=status.HTTP_200_OK)
        except Follow.DoesNotExist:
            return Response({"msg": "Not following"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                f"Failed to unfollow: {e}", status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def is_following(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        try:
            follow = retrieve_follow(user, item)
            serializer = FollowSerializer(follow, context={"request": request})
            return Response(
                {"following": True, "follow": serializer.data},
                status=status.HTTP_200_OK,
            )
        except Follow.DoesNotExist:
            return Response({"following": False}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def following(self, request, *args, **kwargs):
        """List all items the current user is following of this type."""
        user = request.user
        content_type = get_content_type_for_model(self.queryset.model)

        follows = Follow.objects.filter(
            user=user, content_type=content_type
        ).select_related("content_type")

        serializer = FollowSerializer(follows, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAuthenticated & CreateOrUpdateIfAllowed],
    )
    def follow_multiple(self, request):
        """
        Follow multiple items at once.
        Expects: {"ids": [1, 2, 3, ...]}
        """
        item_ids = request.data.get("ids", [])

        if not item_ids:
            return Response(
                {"error": "ids field is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(item_ids, list):
            return Response(
                {"error": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        results = {
            "followed": [],
            "already_following": [],
            "not_found": [],
        }

        # Get all valid items
        model = self.queryset.model
        valid_items = model.objects.filter(id__in=item_ids)

        # Apply any queryset filters (e.g., is_removed=False for hubs)
        if hasattr(self, "get_queryset"):
            base_qs = self.get_queryset()
            valid_items = valid_items.filter(
                id__in=base_qs.values_list("id", flat=True)
            )

        valid_item_ids = set(valid_items.values_list("id", flat=True))

        # Track not found items
        results["not_found"] = list(set(item_ids) - valid_item_ids)

        # Process each item
        for item in valid_items:
            try:
                with transaction.atomic():
                    create_follow(user, item)
                    results["followed"].append(self._serialize_item_for_bulk(item))
            except IntegrityError:
                # Already following
                results["already_following"].append(self._serialize_item_for_bulk(item))
            except Exception as e:
                # Log the error but don't include in response
                logger.error(
                    f"Error following {model.__name__} {item.id} "
                    f"for user {user.id}: {str(e)}"
                )

        return Response(results, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAuthenticated & CreateOrUpdateIfAllowed],
    )
    def unfollow_multiple(self, request):
        """
        Unfollow multiple items at once.
        Expects: {"ids": [1, 2, 3, ...]}
        """
        item_ids = request.data.get("ids", [])

        if not item_ids:
            return Response(
                {"error": "ids field is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(item_ids, list):
            return Response(
                {"error": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        results = {"unfollowed": [], "not_following": [], "not_found": []}

        # Get all valid items
        model = self.queryset.model
        valid_items = model.objects.filter(id__in=item_ids)

        # Apply any queryset filters (e.g., is_removed=False for hubs)
        if hasattr(self, "get_queryset"):
            base_qs = self.get_queryset()
            valid_items = valid_items.filter(
                id__in=base_qs.values_list("id", flat=True)
            )

        valid_item_ids = set(valid_items.values_list("id", flat=True))

        # Track not found items
        results["not_found"] = list(set(item_ids) - valid_item_ids)

        # Process each item
        for item in valid_items:
            try:
                follow = retrieve_follow(user, item)
                follow.delete()
                results["unfollowed"].append(self._serialize_item_for_bulk(item))
            except Follow.DoesNotExist:
                results["not_following"].append(self._serialize_item_for_bulk(item))
            except Exception as e:
                # Log the error but don't include in response
                logger.error(
                    f"Error unfollowing {model.__name__} {item.id} "
                    f"for user {user.id}: {str(e)}"
                )

        return Response(results, status=status.HTTP_200_OK)

    def _serialize_item_for_bulk(self, item):
        """
        Serialize an item for bulk follow/unfollow response.
        Override this method in your ViewSet to customize the response format.
        """
        result = {"id": item.id}

        # Add common fields if they exist
        if hasattr(item, "name"):
            result["name"] = item.name
        if hasattr(item, "slug"):
            result["slug"] = item.slug
        if hasattr(item, "title"):
            result["title"] = item.title

        return result


def create_follow(user, item):
    """Creates a follow relationship between user and item."""
    follow = Follow(
        user=user, content_type=get_content_type_for_model(item), object_id=item.id
    )
    follow.save()

    # Invalidate feed cache when following anything (hub, user, author, etc.)
    # as it affects what content appears in the user's "following" feed
    FeedViewMixin.invalidate_feed_cache_for_user(user.id)

    return follow


def retrieve_follow(user, item):
    """Retrieves a follow relationship between user and item if it exists."""
    return Follow.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        user=user,
    )
