from django.contrib.admin.options import get_content_type_for_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user.related_models.follow_model import Follow
from user.serializers import FollowSerializer
from utils.permissions import CreateOrUpdateIfAllowed


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
            with transaction.atomic():
                follow = create_follow(user, item)
                serializer = FollowSerializer(follow, context={"request": request})
                return Response(serializer.data, status=201)
        except IntegrityError:
            return Response(
                {"msg": "Already following"},
                status=status.HTTP_409_CONFLICT,
            )
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
            follow.delete()
            return Response(serialized_data, status=200)
        except Follow.DoesNotExist:
            return Response({"msg": "Not following"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(f"Failed to unfollow: {e}", status=400)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def is_following(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        try:
            follow = retrieve_follow(user, item)
            serializer = FollowSerializer(follow, context={"request": request})
            return Response({"following": True, "follow": serializer.data}, status=200)
        except Follow.DoesNotExist:
            return Response({"following": False}, status=200)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def following(self, request, *args, **kwargs):
        """List all items the current user is following of this type."""
        user = request.user
        content_type = get_content_type_for_model(self.queryset.model)

        follows = Follow.objects.filter(
            user=user, content_type=content_type
        ).select_related("content_type")

        serializer = FollowSerializer(follows, many=True, context={"request": request})
        return Response(serializer.data)


def create_follow(user, item):
    """Creates a follow relationship between user and item."""
    follow = Follow(
        user=user, content_type=get_content_type_for_model(item), object_id=item.id
    )
    follow.save()
    return follow


def retrieve_follow(user, item):
    """Retrieves a follow relationship between user and item if it exists."""
    return Follow.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        user=user,
    )
