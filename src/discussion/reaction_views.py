from django.contrib.admin.options import get_content_type_for_model
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from discussion.permissions import (
    CensorDiscussion as CensorDiscussionPermission,
    Endorse as EndorsePermission,
    Vote as VotePermission,
)
from discussion.models import Endorsement, Flag, Vote
from discussion.reaction_serializers import (
    EndorsementSerializer,
    FlagSerializer,
    VoteSerializer,
)
from reputation.tasks import create_contribution
from reputation.models import Contribution
from researchhub_document.utils import reset_unified_document_cache
from utils.permissions import CreateOrUpdateIfAllowed
from utils.siftscience import (
  decisions_api,
  events_api,
  update_user_risk_score
)


class ReactionViewActionMixin:
    """
    Note: Action decorators may be applied by classes inheriting this one.
    """

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            EndorsePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def endorse(self, request, pk=None):
        item = self.get_object()
        user = request.user

        try:
            endorsement = create_endorsement(user, item)
            serialized = EndorsementSerializer(endorsement)
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create endorsement: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    @endorse.mapping.delete
    def delete_endorse(self, request, pk=None):
        item = self.get_object()
        user = request.user
        try:
            endorsement = retrieve_endorsement(user, item)
            endorsement_id = endorsement.id
            endorsement.delete()
            return Response(endorsement_id, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete endorsement: {e}',
                status=400
            )

    def flag(self, request, pk=None):
        item = self.get_object()
        user = request.user
        reason = request.data.get('reason')

        try:
            flag = create_flag(user, item, reason)
            serialized = FlagSerializer(flag)

            content_id = f'{type(item).__name__}_{item.id}'
            events_api.track_flag_content(
                item.created_by,
                content_id,
                user.id
            )
            return Response(serialized.data, status=201)
        except Exception as e:
            return Response(
                f'Failed to create flag: {e}',
                status=status.HTTP_400_BAD_REQUEST
            )

    def delete_flag(self, request, pk=None):
        item = self.get_object()
        user = request.user
        try:
            flag = retrieve_flag(user, item)
            serialized = FlagSerializer(flag)
            flag.delete()
            return Response(serialized.data, status=200)
        except Exception as e:
            return Response(
                f'Failed to delete flag: {e}',
                status=400
            )

    @action(
        detail=True,
        methods=['put', 'patch', 'delete'],
        permission_classes=[
            IsAuthenticated,
            CensorDiscussionPermission
        ]
    )
    def censor(self, request, pk=None):
        item = self.get_object()
        item.remove_nested()
        item.update_discussion_count()

        content_id = f'{type(item).__name__}_{item.id}'
        user = request.user
        content_creator = item.created_by
        events_api.track_flag_content(
            content_creator,
            content_id,
            user.id
        )
        decisions_api.apply_bad_content_decision(
            content_creator,
            content_id,
            'MANUAL_REVIEW',
            user
        )

        content_type = get_content_type_for_model(item)
        Contribution.objects.filter(
            content_type=content_type,
            object_id=item.id
        ).delete()
        return Response(
            self.get_serializer(instance=item).data,
            status=200
        )

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def upvote(self, request, pk=None):
        item = self.get_object()
        user = request.user
        vote_exists = find_vote(user, item, Vote.UPVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.UPVOTE)
        return response

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[
            VotePermission
            & CreateOrUpdateIfAllowed
        ]
    )
    def downvote(self, request, pk=None):
        item = self.get_object()
        user = request.user

        vote_exists = find_vote(user, item, Vote.DOWNVOTE)

        if vote_exists:
            return Response(
                'This vote already exists',
                status=status.HTTP_400_BAD_REQUEST
            )
        response = update_or_create_vote(request, user, item, Vote.DOWNVOTE)
        return response

    @action(detail=True, methods=['get'])
    def user_vote(self, request, pk=None):
        item = self.get_object()
        user = request.user
        vote = retrieve_vote(user, item)
        return get_vote_response(vote, 200)

    @user_vote.mapping.delete
    def delete_user_vote(self, request, pk=None):
        try:
            item = self.get_object()
            user = request.user
            vote = retrieve_vote(user, item)
            vote_id = vote.id
            vote.delete()
            return Response(vote_id, status=200)
        except Exception as e:
            return Response(f'Failed to delete vote: {e}', status=400)

    def get_ordering(self):
        default_ordering = ['-score', 'created_date']

        ordering = self.request.query_params.get('ordering', default_ordering)
        if isinstance(ordering, str):
            if ordering and 'created_date' not in ordering:
                ordering = [ordering, 'created_date']
            elif 'created_date' not in ordering:
                ordering = ['created_date']
            else:
                ordering = [ordering]
        return ordering

    def get_action_context(self):

        ordering = self.get_ordering()
        needs_score = False
        if 'score' in ordering or '-score' in ordering:
            needs_score = True
        return {
            'ordering': ordering,
            'needs_score': needs_score,
        }

    def get_self_upvote_response(self, request, response, model):
        """Returns item in response data with upvote from creator and score."""
        item = model.objects.get(pk=response.data['id'])
        create_vote(request.user, item, Vote.UPVOTE)

        serializer = self.get_serializer(item)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def sift_track_create_content_comment(
        self,
        request,
        response,
        model,
        is_thread=False
    ):
        item = model.objects.get(pk=response.data['id'])
        tracked_comment = events_api.track_content_comment(
            item.created_by,
            item,
            request,
            is_thread=is_thread
        )
        update_user_risk_score(item.created_by, tracked_comment)

    def sift_track_update_content_comment(
        self,
        request,
        response,
        model,
        is_thread=False
    ):
        item = model.objects.get(pk=response.data['id'])
        tracked_comment = events_api.track_content_comment(
            item.created_by,
            item,
            request,
            is_thread=is_thread,
            update=True
        )
        update_user_risk_score(item.created_by, tracked_comment)


def retrieve_endorsement(user, item):
    return Endorsement.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id
    )


def create_endorsement(user, item):
    endorsement = Endorsement(created_by=user, item=item)
    endorsement.save()
    return endorsement


def create_flag(user, item, reason):
    flag = Flag(created_by=user, item=item, reason=reason)
    flag.save()
    return flag


def find_vote(user, item, vote_type):
    vote = Vote.objects.filter(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user,
        vote_type=vote_type
    )
    if vote:
        return True
    return False


def retrieve_flag(user, item):
    return Flag.objects.get(
        object_id=item.id,
        content_type=get_content_type_for_model(item),
        created_by=user.id
    )


def retrieve_vote(user, item):
    try:
        return Vote.objects.get(
            object_id=item.id,
            content_type=get_content_type_for_model(item),
            created_by=user.id
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
    vote = retrieve_vote(user, item)
    # TODO: calvinhlee - figure out how to handle contributions
    if vote is not None:
        vote.vote_type = vote_type
        vote.save(update_fields=['updated_date', 'vote_type'])
        reset_unified_document_cache([0])
        # events_api.track_content_vote(user, vote, request)
        return get_vote_response(vote, 200)

    vote = create_vote(user, item, vote_type)
    reset_unified_document_cache([0])

    # app_label = item._meta.app_label
    # model = item._meta.model
    # events_api.track_content_vote(user, vote, request)
    # create_contribution.apply_async(
    #     (
    #         Contribution.UPVOTER,
    #         {'app_label': app_label, 'model': model},
    #         request.user.id,
    #         vote.paper.id,
    #         vote.id
    #     ),
    #     priority=2,
    #     countdown=10
    # )
    return get_vote_response(vote, 201)
