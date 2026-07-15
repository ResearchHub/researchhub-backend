import logging

from django.contrib.admin.options import get_content_type_for_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from discussion.models import Flag, Vote
from discussion.permissions import CensorDiscussion as CensorDiscussionPermission
from discussion.permissions import EditorCensorDiscussion
from discussion.permissions import Vote as VotePermission
from discussion.serializers import FlagSerializer, VoteSerializer
from discussion.services import VoteService
from feed.views.grant_cache_mixin import GrantCacheMixin
from researchhub_document.related_models.constants.document_type import SORT_UPVOTED
from utils.models import SoftDeletableModel
from utils.permissions import CreateOrUpdateIfAllowed

logger = logging.getLogger(__name__)


def censor(item):
    if isinstance(item, SoftDeletableModel):
        item.delete(soft=True)
    else:
        item.unified_document.delete(soft=True)

    if reviews := getattr(item, "reviews", None):
        reviews.all().update(
            is_removed=True, is_public=False, is_removed_date=timezone.now()
        )

    if (action := getattr(item, "actions", None)) and action.exists():
        action = action.first()
        action.is_removed = True
        action.display = False
        action.save(update_fields=["is_removed", "display"])

    if purchases := getattr(item, "purchases", None):
        for purchase in purchases.iterator():
            purchase.actions.update(is_removed=True, display=False)

    GrantCacheMixin.invalidate_if_grant_linked(getattr(item, "unified_document", None))

    return True


class ReactionViewActionMixin:
    """
    Note: Action decorators may be applied by classes inheriting this one.
    """

    vote_service = VoteService()

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated],
    )
    def flag(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        reason = request.data.get("reason")
        reason_choice = request.data.get("reason_choice")
        reason_memo = request.data.get("reason_memo")

        try:
            _, flag_data = create_flag(user, item, reason, reason_choice, reason_memo)

            return Response(flag_data, status=201)
        except (IntegrityError, ValidationError):
            return Response(
                {
                    "msg": "Already flagged",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except Exception as e:
            logger.exception("Failed to create flag for item %s", item.id)
            return Response(
                {
                    "detail": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete_flag(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        try:
            flag = retrieve_flag(user, item)
            serialized = FlagSerializer(flag)
            flag.delete()
            return Response(serialized.data, status=200)
        except Exception as e:
            logger.exception("Failed to delete flag for item %s", item.id)
            return Response(f"Failed to delete flag: {e}", status=400)

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        permission_classes=[
            IsAuthenticated,
            (CensorDiscussionPermission | EditorCensorDiscussion),
        ],
    )
    def censor(self, request, *args, pk=None, **kwargs):
        item = self.get_object()

        with transaction.atomic():
            censor(item)
            return Response(
                self.get_serializer(instance=item, _include_fields=("id",)).data,
                status=200,
            )

    @track_event
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated & VotePermission & CreateOrUpdateIfAllowed],
    )
    def upvote(self, request, *args, pk=None, **kwargs):
        with transaction.atomic():
            item = self.get_object()
            user = request.user
            vote_exists = self.vote_service.find_vote(user, item, Vote.UPVOTE)
            if vote_exists:
                return Response(
                    "This vote already exists", status=status.HTTP_400_BAD_REQUEST
                )
            vote, created = self.vote_service.update_or_create_vote(
                user, item, Vote.UPVOTE
            )
            item.unified_document.update_filter(SORT_UPVOTED)
            return Response(
                VoteSerializer(vote).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated & VotePermission & CreateOrUpdateIfAllowed],
    )
    def neutralvote(self, request, *args, pk=None, **kwargs):
        with transaction.atomic():
            item = self.get_object()
            user = request.user
            vote_exists = self.vote_service.find_vote(user, item, Vote.NEUTRAL)

            if vote_exists:
                return Response(
                    "This vote already exists", status=status.HTTP_400_BAD_REQUEST
                )
            vote, created = self.vote_service.update_or_create_vote(
                user, item, Vote.NEUTRAL
            )
            return Response(
                VoteSerializer(vote).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

    @track_event
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated & VotePermission & CreateOrUpdateIfAllowed],
    )
    def downvote(self, request, *args, pk=None, **kwargs):
        with transaction.atomic():
            item = self.get_object()
            user = request.user

            vote_exists = self.vote_service.find_vote(user, item, Vote.DOWNVOTE)

            if vote_exists:
                return Response(
                    "This vote already exists", status=status.HTTP_400_BAD_REQUEST
                )
            vote, created = self.vote_service.update_or_create_vote(
                user, item, Vote.DOWNVOTE
            )
            item.unified_document.update_filter(SORT_UPVOTED)
            return Response(
                VoteSerializer(vote).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )

    @action(detail=True, methods=["get"])
    def user_vote(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        vote = self.vote_service.retrieve_vote(user, item)
        return Response(VoteSerializer(vote).data, status=status.HTTP_200_OK)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, *args, pk=None, **kwargs):
        try:
            item = self.get_object()
            user = request.user
            vote = self.vote_service.retrieve_vote(user, item)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f"Failed to delete vote: {e}", status=400)

    def get_action_context(self):
        return {
            "ordering": [
                "created_date",
                "-score",
            ],
            "needs_score": True,
        }

    def add_upvote(self, user, obj):
        vote = self.vote_service.create_vote(user, obj, Vote.UPVOTE)
        obj.score += 1
        obj.save()
        return vote

    def add_downvote(self, user, obj):
        vote = self.vote_service.create_vote(user, obj, Vote.DOWNVOTE)
        obj.score -= 1
        obj.save()
        return vote


def create_flag(user, item, reason, reason_choice, reason_memo=None):
    with transaction.atomic():
        data = {
            "created_by": user.id,
            "object_id": item.id,
            "content_type": get_content_type_for_model(item).id,
            "reason": reason or reason_choice,
            "reason_choice": reason_choice or reason,
            # Default to empty string to match model default and avoid nulls
            "reason_memo": reason_memo or "",
        }
        serializer = FlagSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        flag = serializer.save()
        flag.hubs.add(*item.unified_document.hubs.all())
        return flag, serializer.data


def retrieve_flag(user, item):
    return Flag.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id,
    )
