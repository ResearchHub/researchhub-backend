from django.contrib.admin.options import get_content_type_for_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from discussion.models import Comment, Reply, Thread
from discussion.permissions import CensorDiscussion as CensorDiscussionPermission
from discussion.permissions import EditorCensorDiscussion
from discussion.permissions import Endorse as EndorsePermission
from discussion.permissions import Vote as VotePermission
from discussion.reaction_models import Endorsement, Flag, Vote
from discussion.reaction_serializers import (
    EndorsementSerializer,
    FlagSerializer,
    VoteSerializer,
)
from reputation.models import Contribution
from reputation.tasks import create_contribution
from researchhub_document.related_models.constants.document_type import SORT_UPVOTED
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    HOT,
    UPVOTED,
)
from researchhub_document.utils import get_doc_type_key, reset_unified_document_cache
from utils.permissions import CreateOrUpdateIfAllowed
from utils.sentry import log_error
from utils.siftscience import decisions_api, events_api, update_user_risk_score


class ReactionViewActionMixin:
    """
    Note: Action decorators may be applied by classes inheriting this one.
    """

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[EndorsePermission & CreateOrUpdateIfAllowed],
    )
    def endorse(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user

        try:
            endorsement = create_endorsement(user, item)
            serialized = EndorsementSerializer(endorsement)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f"Failed to create endorsement: {e}", status=status.HTTP_400_BAD_REQUEST
            )

    @endorse.mapping.delete
    def delete_endorse(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        try:
            endorsement = retrieve_endorsement(user, item)
            endorsement_id = endorsement.id
            endorsement.delete()
            return Response(endorsement_id, status=200)
        except Exception as e:
            return Response(f"Failed to delete endorsement: {e}", status=400)

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

        try:
            flag, flag_data = create_flag(user, item, reason, reason_choice)

            content_id = f"{type(item).__name__}_{item.id}"
            events_api.track_flag_content(item.created_by, content_id, user.id)
            return Response(flag_data, status=201)
        except IntegrityError as e:
            return Response(
                {
                    "msg": "Already flagged",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except Exception as e:
            log_error(e)
            return Response(
                {
                    "detail": e,
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
            content_id = f"{type(item).__name__}_{item.id}"
            user = request.user
            content_creator = item.created_by
            events_api.track_flag_content(content_creator, content_id, user.id)
            decisions_api.apply_bad_content_decision(
                content_creator, content_id, "MANUAL_REVIEW", user
            )

            try:
                if item.review:
                    item.review.is_removed = True
                    item.review.save()

                doc = item.unified_document
                if doc.bounties.exists():
                    for bounty in doc.bounties.iterator():
                        bounty.cancel()
                        bounty.save()

                action = getattr(item, "actions", None)
                if action.exists():
                    action = action.first()
                    action.is_removed = True
                    action.display = False
                    action.save()

                doc_type = get_doc_type_key(doc)
                hubs = list(doc.hubs.all().values_list("id", flat=True))

                reset_unified_document_cache(
                    hub_ids=hubs,
                    document_type=[doc_type, "all"],
                    filters=[DISCUSSED, HOT],
                )

                # Commenting out paper cache
                # if item.paper:
                #     item.paper.reset_cache()
            except Exception as e:
                print(e)
                log_error(e)
                return Response({"detail": str(e)}, status=500)

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
            vote_exists = find_vote(user, item, Vote.UPVOTE)
            if vote_exists:
                return Response(
                    "This vote already exists", status=status.HTTP_400_BAD_REQUEST
                )
            response = update_or_create_vote(request, user, item, Vote.UPVOTE)
            item.unified_document.update_filter(SORT_UPVOTED)
            return response

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated & VotePermission & CreateOrUpdateIfAllowed],
    )
    def neutralvote(self, request, *args, pk=None, **kwargs):
        with transaction.atomic():
            item = self.get_object()
            user = request.user
            vote_exists = find_vote(user, item, Vote.NEUTRAL)

            if vote_exists:
                return Response(
                    "This vote already exists", status=status.HTTP_400_BAD_REQUEST
                )
            response = update_or_create_vote(request, user, item, Vote.NEUTRAL)
            return response

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

            vote_exists = find_vote(user, item, Vote.DOWNVOTE)

            if vote_exists:
                return Response(
                    "This vote already exists", status=status.HTTP_400_BAD_REQUEST
                )
            response = update_or_create_vote(request, user, item, Vote.DOWNVOTE)
            item.unified_document.update_filter(SORT_UPVOTED)
            return response

    @action(detail=True, methods=["get"])
    def user_vote(self, request, *args, pk=None, **kwargs):
        item = self.get_object()
        user = request.user
        vote = retrieve_vote(user, item)
        return get_vote_response(vote, 200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, *args, pk=None, **kwargs):
        try:
            item = self.get_object()
            user = request.user
            vote = retrieve_vote(user, item)
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

    def get_self_upvote_response(self, request, response, model):
        """Returns item in response data with upvote from creator and score."""
        item = model.objects.get(pk=response.data["id"])
        create_vote(request.user, item, Vote.UPVOTE)

        serializer = self.get_serializer(item)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def sift_track_create_content_comment(
        self, request, response, model, is_thread=False
    ):
        item = model.objects.get(pk=response.data["id"])
        tracked_comment = events_api.track_content_comment(
            item.created_by, item, request, is_thread=is_thread
        )
        update_user_risk_score(item.created_by, tracked_comment)

    def sift_track_update_content_comment(
        self, request, response, model, is_thread=False
    ):
        item = model.objects.get(pk=response.data["id"])
        tracked_comment = events_api.track_content_comment(
            item.created_by, item, request, is_thread=is_thread, update=True
        )
        update_user_risk_score(item.created_by, tracked_comment)


def retrieve_endorsement(user, item):
    return Endorsement.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id,
    )


def create_endorsement(user, item):
    endorsement = Endorsement(created_by=user, item=item)
    endorsement.save()
    return endorsement


def create_flag(user, item, reason, reason_choice):
    with transaction.atomic():
        data = {
            "created_by": user.id,
            "object_id": item.id,
            "content_type": get_content_type_for_model(item).id,
            "reason": reason or reason_choice,
            "reason_choice": reason_choice,
        }
        serializer = FlagSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        flag = serializer.save()
        flag.hubs.add(*item.unified_document.hubs.all())
        return flag, serializer.data


def find_vote(user, item, vote_type):
    vote = Vote.objects.filter(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user,
        vote_type=vote_type,
    )
    if vote:
        return True
    return False


def retrieve_flag(user, item):
    return Flag.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id,
    )


def retrieve_vote(user, item):
    try:
        return Vote.objects.get(
            object_id=item.id,
            content_type=get_content_type_for_model(item),
            created_by=user.id,
        )
    except Vote.DoesNotExist:
        return None


def get_vote_response(vote, status_code):
    serializer = VoteSerializer(vote)
    return Response(serializer.data, status=status_code)


def create_vote(user, item, vote_type):
    """Returns a vote of `voted_type` on `item` `created_by` `user`."""
    vote = Vote(created_by=user, item=item, vote_type=vote_type)
    vote.save()
    return vote


def update_or_create_vote(request, user, item, vote_type):
    cache_filters_to_reset = [UPVOTED, HOT]
    if isinstance(item, (Thread, Comment, Reply)):
        cache_filters_to_reset = [HOT]

    hub_ids = [0]
    # NOTE: Hypothesis citations do not have a unified document attached
    has_unified_doc = hasattr(item, "unified_document")

    if has_unified_doc:
        hub_ids += list(item.unified_document.hubs.values_list("id", flat=True))

    """UPDATE VOTE"""
    vote = retrieve_vote(user, item)
    if vote is not None:
        vote.vote_type = vote_type
        vote.save(update_fields=["updated_date", "vote_type"])
        if has_unified_doc:
            update_relavent_doc_caches_on_vote(
                cache_filters_to_reset=cache_filters_to_reset,
                hub_ids=hub_ids,
                target_vote=vote,
            )

        # events_api.track_content_vote(user, vote, request)
        return get_vote_response(vote, 200)

    """CREATE VOTE"""
    vote = create_vote(user, item, vote_type)
    if has_unified_doc:
        update_relavent_doc_caches_on_vote(
            cache_filters_to_reset=cache_filters_to_reset,
            hub_ids=hub_ids,
            target_vote=vote,
        )

    # potential_paper = vote.item
    # from paper.models import Paper

    # Commenting out paper cache
    # if isinstance(potential_paper, Paper):
    #     potential_paper.reset_cache()

    app_label = item._meta.app_label
    model = item._meta.model.__name__.lower()
    # events_api.track_content_vote(user, vote, request)
    create_contribution.apply_async(
        (
            Contribution.UPVOTER,
            {"app_label": app_label, "model": model},
            request.user.id,
            vote.unified_document.id,
            vote.id,
        ),
        priority=2,
        countdown=10,
    )
    return get_vote_response(vote, 201)


def update_relavent_doc_caches_on_vote(cache_filters_to_reset, hub_ids, target_vote):
    item = target_vote.item
    doc_type = get_doc_type_key(item.unified_document)
    reset_unified_document_cache(
        hub_ids, document_type=[doc_type, "all"], filters=cache_filters_to_reset
    )

    # Commenting out paper cache
    # from paper.models import Paper

    # if isinstance(item, Paper):
    #     item.reset_cache()
