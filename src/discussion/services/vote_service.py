import logging

from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from discussion.models import Vote
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
)
from user.models import User

logger = logging.getLogger(__name__)


class VoteService:
    """
    Service for casting and looking up votes on reactable items.
    """

    def find_vote(self, user, item, vote_type) -> bool:
        """Return whether `user` already has a vote of `vote_type` on `item`."""
        return Vote.objects.filter(
            object_id=item.id,
            content_type=get_content_type_for_model(item),
            created_by=user,
            vote_type=vote_type,
        ).exists()

    def retrieve_vote(self, user, item):
        """Return `user`'s vote on `item`, or None if there isn't one."""
        try:
            return Vote.objects.get(
                object_id=item.id,
                content_type=get_content_type_for_model(item),
                created_by=user.id,
            )
        except Vote.DoesNotExist:
            return None

    def create_vote(self, user, item, vote_type):
        """Create and return a vote of `vote_type` on `item` `created_by` `user`."""
        return Vote.objects.create(created_by=user, item=item, vote_type=vote_type)

    def update_or_create_vote(self, user, item, vote_type):
        """
        Apply `user`'s `vote_type` to `item`, updating an existing vote or
        creating a new one.

        Returns a `(vote, created)` tuple where `created` is True when a new
        vote was created and False when an existing vote was updated.
        """
        vote = self.retrieve_vote(user, item)
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
            # If we're in the biorxiv review hub, we want all papers with 10 upvotes
            # to get an automatic peer review
            self._create_automated_bounty(item)
        except Exception:
            logger.exception("Failed to create automated bounty for item %s", item.id)

        if vote is not None:
            vote.vote_type = vote_type
            vote.save(update_fields=["updated_date", "vote_type"])
            return vote, False

        vote = self.create_vote(user, item, vote_type)

        app_label = item._meta.app_label
        model = item._meta.model.__name__.lower()
        create_contribution.apply_async(
            (
                Contribution.UPVOTER,
                {"app_label": app_label, "model": model},
                user.id,
                vote.unified_document.id,
                vote.id,
            ),
            priority=2,
            countdown=10,
        )
        return vote, True

    def _create_automated_bounty(self, item):
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
                amount = str(
                    RscExchangeRate.usd_to_rsc(usd_amount_for_bounty) // 10 * 10
                )
                bypass_user_balance = True
                json_content = {
                    "ops": [
                        {
                            "insert": "ResearchHub Foundation is assigning an incentive of "  # noqa: E501
                        },
                        {
                            "attributes": {"bold": True},
                            "insert": "$150 in ResearchCoin (RSC)",
                        },
                        {
                            "insert": " for a high-quality, rigorous, and constructive peer review of this manuscript. If your expertise aligns well with this research, please consider posting your review.\n\n"  # noqa: E501
                        },
                        {"attributes": {"bold": True}, "insert": "Requirements:"},
                        {
                            "insert": "\nVerify identity and complete profile (including ORCID auth) on ResearchHub."  # noqa: E501
                        },
                        {"attributes": {"list": "ordered"}, "insert": "\n"},
                        {
                            "insert": "Submit your review within 14 days of the date this bounty was initiated."  # noqa: E501
                        },
                        {"attributes": {"list": "ordered"}, "insert": "\n"},
                        {
                            "insert": "Describe the relevance of your domain expertise to the manuscript."  # noqa: E501
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
                            "insert": 'Use the rating system in the "Peer Reviews" tab for all 5 criteria: overall assessment, introduction, methods, results, and discussion. Please read our '  # noqa: E501
                        },
                        {
                            "attributes": {
                                "link": "https://docs.researchhub.com/researchhub-foundation/programs-and-initiatives/peer-review-program/peer-review-program-guidelines"
                            },
                            "insert": "Peer Review Guide",
                        },
                        {
                            "insert": " with details about the process and examples of awarded reviews. Please avoid using other review formats."  # noqa: E501
                        },
                        {"attributes": {"list": "ordered"}, "insert": "\n"},
                        {
                            "insert": "\nEditors will review and award up to 2 high-quality peer reviews within 1 week following the 14 day submission window. All decisions are final. For questions, please contact "  # noqa: E501
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
