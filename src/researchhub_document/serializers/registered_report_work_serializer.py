from typing import Any

from django.core.files.storage import default_storage
from rest_framework import serializers

from feed.hot_score_utils import calculate_adjusted_score
from feed.models import FeedEntry
from feed.serializers import SimpleAuthorSerializer, SimpleUserSerializer
from note.models import parse_note_json
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_STAGE_GRANT,
    JOURNEY_STAGE_PROPOSAL,
    JOURNEY_STAGE_REGISTERED_REPORT,
)
from researchhub_document.services.registered_report_work_service import (
    RegisteredReportWorkPayload,
)
from review.serializers.review_serializer import DynamicReviewSerializer


class RegisteredReportWorkSerializer(serializers.Serializer):
    """Serialize one registered report work-page payload."""

    def to_representation(self, payload: RegisteredReportWorkPayload) -> dict[str, Any]:
        """Return feed-like registered report data plus tracker post references."""
        report = payload.report
        authors = self.serialize_authors(report)

        return {
            "id": report.id,
            "content_type": report._meta.model_name.upper(),
            "content_object": self.serialize_content_object(
                report,
                payload.proposal,
                authors,
            ),
            "action_date": report.created_date,
            "action": FeedEntry.PUBLISH,
            "author": self.serialize_author(report),
            "metrics": self.serialize_metrics(report),
            "work": self.serialize_work(report, authors),
            "tracker": [
                self.serialize_tracker_step(
                    JOURNEY_STAGE_GRANT,
                    "Grant",
                    payload.grant,
                    is_current=False,
                ),
                self.serialize_tracker_step(
                    JOURNEY_STAGE_PROPOSAL,
                    "Proposal",
                    payload.proposal,
                    is_current=False,
                ),
                self.serialize_tracker_step(
                    JOURNEY_STAGE_REGISTERED_REPORT,
                    "Registered Report",
                    report,
                    is_current=True,
                ),
            ],
        }

    def serialize_content_object(
        self,
        post: ResearchhubPost,
        proposal: ResearchhubPost | None,
        authors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Serialize the registered report card data without feed-only extras."""
        return {
            "id": post.id,
            "slug": post.slug,
            "title": post.title,
            "type": post.document_type,
            "doi": post.doi,
            "image_url": self.get_image_url(post),
            "unified_document_id": post.unified_document_id,
            "authors": authors,
            "journal_state": JOURNEY_STAGE_REGISTERED_REPORT,
            "proposal": self.serialize_proposal_reference(proposal),
        }

    def serialize_work(
        self, post: ResearchhubPost, authors: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Serialize registered report work data for the work page."""
        return {
            "id": post.id,
            "authors": authors,
            "created_by": self.serialize_created_by(post),
            "created_date": post.created_date,
            "document_type": post.document_type,
            "doi": post.doi,
            "editor_type": post.editor_type,
            "full_json": self.get_full_json(post),
            "image_url": self.get_image_url(post),
            "is_removed": post.unified_document.is_removed,
            "preview_img": post.preview_img,
            "renderable_text": post.renderable_text,
            "slug": post.slug,
            "status": post.unified_document.status,
            "title": post.title,
            "unified_document_id": post.unified_document_id,
            "updated_date": post.updated_date,
        }

    def serialize_tracker_step(
        self,
        stage: str,
        label: str,
        post: ResearchhubPost | None,
        is_current: bool,
    ) -> dict[str, Any]:
        """Serialize one ordered tracker stage and its post reference."""
        return {
            "stage": stage,
            "label": label,
            "exists": post is not None,
            "is_current": is_current,
            "post_id": post.id if post is not None else None,
            "title": post.title if post is not None else None,
            "document_type": post.document_type if post is not None else None,
        }

    def serialize_proposal_reference(
        self, proposal: ResearchhubPost | None
    ) -> dict[str, Any] | None:
        """Serialize source-proposal data needed by the work-page sidebar."""
        if proposal is None:
            return None
        return {
            "id": proposal.id,
            "slug": proposal.slug,
            "title": proposal.title,
            "doi": proposal.doi,
            "authors": self.serialize_authors(proposal),
            "created_by": self.serialize_created_by(proposal),
            "created_date": proposal.created_date,
            "document_type": proposal.document_type,
            "image_url": self.get_image_url(proposal),
            "peer_reviews": self.serialize_peer_reviews(proposal),
            "status": proposal.unified_document.status,
            "unified_document_id": proposal.unified_document_id,
            "updated_date": proposal.updated_date,
        }

    def serialize_peer_reviews(self, proposal: ResearchhubPost) -> list[dict[str, Any]]:
        """Serialize proposal reviews with each reviewer's profile image."""
        return DynamicReviewSerializer(
            proposal.unified_document.reviews.all(),
            many=True,
            _include_fields=[
                "id",
                "score",
                "is_assessed",
                "created_by",
                "created_date",
                "updated_date",
            ],
            context={
                **self.context,
                "rev_drs_get_created_by": {
                    "_include_fields": [
                        "id",
                        "author_profile",
                        "first_name",
                        "is_verified",
                        "last_name",
                    ]
                },
                "usr_dus_get_author_profile": {
                    "_include_fields": [
                        "id",
                        "first_name",
                        "last_name",
                        "profile_image",
                    ]
                },
            },
        ).data

    def serialize_authors(self, post: ResearchhubPost) -> list[dict[str, Any]]:
        """Serialize registered report authors."""
        authors = post.ordered_authors
        if not authors and post.created_by is not None:
            authors = [post.created_by.author_profile]
        return SimpleAuthorSerializer(authors, context=self.context, many=True).data

    def serialize_author(self, post: ResearchhubPost) -> dict[str, Any] | None:
        """Serialize the feed author."""
        author = getattr(post.created_by, "author_profile", None)
        if author is None:
            return None
        return SimpleAuthorSerializer(author).data

    def serialize_created_by(self, post: ResearchhubPost) -> dict[str, Any] | None:
        """Serialize the report creator without account-only fields."""
        if post.created_by is None:
            return None
        return SimpleUserSerializer(post.created_by).data

    def serialize_metrics(self, post: ResearchhubPost) -> dict[str, Any]:
        """Serialize registered report metrics without conversations or reviews."""
        votes = getattr(post, "score", 0)
        return {
            "votes": votes,
            "adjusted_score": calculate_adjusted_score(votes, {}),
        }

    def get_image_url(self, post: ResearchhubPost) -> str | None:
        """Return the registered report image URL."""
        if not post.image:
            return None
        return default_storage.url(post.image)

    def get_full_json(self, post: ResearchhubPost) -> dict[str, Any] | None:
        """Return the notebook JSON used to render the registered report."""
        note = post.note
        if note is None or note.latest_version is None:
            return None

        return parse_note_json(note.latest_version.json)
