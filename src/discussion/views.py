from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from discussion.models import Endorsement, Flag, Vote
from discussion.permissions import CensorDiscussion as CensorDiscussionPermission
from discussion.permissions import EditorCensorDiscussion
from discussion.permissions import Endorse as EndorsePermission
from discussion.permissions import Vote as VotePermission
from discussion.serializers import EndorsementSerializer, FlagSerializer, VoteSerializer
from paper.models import Paper
from purchase.models import RscExchangeRate
from reputation.models import Contribution
from reputation.tasks import create_contribution
from reputation.views.bounty_view import _create_bounty, _create_bounty_checks
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.related_models.constants.document_type import (
    FILTER_BOUNTY_OPEN,
    FILTER_HAS_BOUNTY,
    SORT_BOUNTY_EXPIRATION_DATE,
    SORT_BOUNTY_TOTAL_AMOUNT,
    SORT_DISCUSSED,
    SORT_UPVOTED,
)
from user.models import User
from utils.models import SoftDeletableModel
from utils.permissions import CreateOrUpdateIfAllowed
from utils.sentry import log_error


def censor(item):
    if isinstance(item, SoftDeletableModel):
        item.delete(soft=True)
    else:
        item.unified_document.delete(soft=True)

    if reviews := getattr(item, "reviews", None):
        reviews.all().delete()

    if action := getattr(item, "actions", None):
        if action.exists():
            action = action.first()
            action.is_removed = True
            action.display = False
            action.save(update_fields=["is_removed", "display"])

    if purchases := getattr(item, "purchases", None):
        for purchase in purchases.iterator():
            purchase.actions.update(is_removed=True, display=False)

    return True


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

    def add_upvote(self, user, obj):
        vote = create_vote(user, obj, Vote.UPVOTE)
        obj.score += 1
        obj.save()
        return vote

    def add_downvote(self, user, obj):
        vote = create_vote(user, obj, Vote.DOWNVOTE)
        obj.score -= 1
        obj.save()
        return vote


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
    vote = Vote.objects.create(created_by=user, item=item, vote_type=vote_type)
    return vote


def create_automated_bounty(item):
    if (
        isinstance(item, Paper)
        and item.score >= 3
        and item.hubs.filter(id=436).exists()  # Hardcoded Biorxiv Hub
        and not item.automated_bounty_created
    ):
        with transaction.atomic():
            user = User.objects.get(email="main@researchhub.foundation")
            item_object_id = item.id
            item_content_type = ContentType.objects.get_for_model(item)
            usd_amount_for_bounty = 150

            # Round the number to nearest 10, then turn it into a string
            amount = str(RscExchangeRate.usd_to_rsc(usd_amount_for_bounty) // 10 * 10)
            bypass_user_balance = True
            json_content = {
                "ops": [
                    {"insert": "ResearchHub Foundation is assigning an incentive of "},
                    {
                        "attributes": {"bold": True},
                        "insert": "$150 in ResearchCoin (RSC)",
                    },
                    {
                        "insert": " for a high-quality, rigorous, and constructive peer review of this manuscript. If your expertise aligns well with this research, please consider posting your review.\n\n"
                    },
                    {"attributes": {"bold": True}, "insert": "Requirements:"},
                    {
                        "insert": "\nVerify identity and complete profile (including ORCID auth) on ResearchHub."
                    },
                    {"attributes": {"list": "ordered"}, "insert": "\n"},
                    {
                        "insert": "Submit your review within 14 days of the date this bounty was initiated."
                    },
                    {"attributes": {"list": "ordered"}, "insert": "\n"},
                    {
                        "insert": "Describe the relevance of your domain expertise to the manuscript."
                    },
                    {"attributes": {"list": "ordered"}, "insert": "\n"},
                    {"insert": "Disclose AI use. Please refer to our "},
                    {
                        "attributes": {
                            "link": "https://drive.google.com/file/d/1KihDvQze5rzi8xwleWfMNsdPbc6EF0t_/view"
                        },
                        "insert": "AI Policy",
                    },
                    {"insert": " for additional details."},
                    {"attributes": {"list": "ordered"}, "insert": "\n"},
                    {"insert": "Disclose conflicts of interest."},
                    {"attributes": {"list": "ordered"}, "insert": "\n"},
                    {
                        "insert": 'Use the rating system in the "Peer Reviews" tab for all 5 criteria: overall assessment, introduction, methods, results, and discussion. Please read our '
                    },
                    {
                        "attributes": {
                            "link": "https://blog.researchhub.foundation/peer-reviewing-on-researchhub/"
                        },
                        "insert": "Peer Review Guide",
                    },
                    {
                        "insert": " with details about the process and examples of awarded reviews. Please avoid using other review formats."
                    },
                    {"attributes": {"list": "ordered"}, "insert": "\n"},
                    {
                        "insert": "\nEditors will review and award up to 2 high-quality peer reviews within 1 week following the 14 day submission window. All decisions are final. For questions, please contact "
                    },
                    {
                        "attributes": {
                            "link": "mailto:editorial@researchhub.foundation"
                        },
                        "insert": "editorial@researchhub.foundation",
                    },
                    {"insert": ".\n"},
                ]
            }

            thread = RhCommentThreadModel.objects.create(
                thread_type="GENERIC_COMMENT",
                content_type_id=item_content_type.id,
                created_by=user,
                updated_by=user,
                object_id=item_object_id,
            )

            comment, _ = RhCommentModel.create_from_data(
                {
                    "updated_by": user.id,
                    "created_by": user.id,
                    "comment_content_type": "QUILL_EDITOR",
                    "thread": thread.id,
                    "comment_content_json": json_content,
                }
            )

            comment_content_type = RhCommentModel.__name__.lower()

            data = {
                "item_content_type": comment_content_type,
                "item": comment,
                "item_object_id": comment.id,
                "bounty_type": "REVIEW",
            }

            response = _create_bounty_checks(
                user, amount, comment_content_type, bypass_user_balance
            )
            if not isinstance(response, tuple):
                return response
            else:
                amount, fee_amount, rh_fee, dao_fee, current_bounty_fee = response

            bounty = _create_bounty(
                user,
                data,
                amount,
                fee_amount,
                current_bounty_fee,
                comment_content_type,
                comment.id,
                False,
                rh_fee=rh_fee,
            )
            unified_document = bounty.unified_document
            unified_document.update_filters(
                (
                    FILTER_BOUNTY_OPEN,
                    FILTER_HAS_BOUNTY,
                    SORT_BOUNTY_EXPIRATION_DATE,
                    SORT_BOUNTY_TOTAL_AMOUNT,
                    SORT_DISCUSSED,
                )
            )

            item.automated_bounty_created = True
            item.save(update_fields=["automated_bounty_created"])


def update_or_create_vote(request, user, item, vote_type):
    """UPDATE VOTE"""
    vote = retrieve_vote(user, item)
    if vote_type == Vote.UPVOTE and vote and vote.vote_type == vote.DOWNVOTE:
        item.score += 2
    elif vote_type == Vote.DOWNVOTE and vote and vote.vote_type == vote.UPVOTE:
        item.score -= 2
    elif vote_type == Vote.UPVOTE:
        item.score += 1
    elif vote_type == Vote.DOWNVOTE:
        item.score -= 1
    elif vote_type == Vote.NEUTRAL and vote and vote.vote_type == Vote.UPVOTE:
        item.score -= 1
    elif vote_type == Vote.NEUTRAL and vote and vote.vote_type == Vote.DOWNVOTE:
        item.score += 1

    item.save()

    try:
        # If we're in the biorxiv review hub, we want all papers with 10 upvotes to get an automatic peer review
        create_automated_bounty(item)
    except Exception as e:
        log_error(e)

    if vote is not None:
        vote.vote_type = vote_type
        vote.save(update_fields=["updated_date", "vote_type"])

        return get_vote_response(vote, 200)

    """CREATE VOTE"""
    vote = create_vote(user, item, vote_type)

    app_label = item._meta.app_label
    model = item._meta.model.__name__.lower()
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
