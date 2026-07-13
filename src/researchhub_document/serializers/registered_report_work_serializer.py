from typing import Any

from django.core.files.storage import default_storage
from rest_framework import serializers

from feed.hot_score_utils import calculate_adjusted_score
from feed.models import FeedEntry
from feed.serializers import SimpleAuthorSerializer
from hub.serializers import SimpleHubSerializer
from researchhub_document.models import ResearchhubPost, ResearchJourney
from researchhub_document.registered_report_note_metadata import parse_note_json
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_STAGE_GRANT,
    JOURNEY_STAGE_PROPOSAL,
    JOURNEY_STAGE_REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.serializers import AuthorSerializer, UserSerializer


class RegisteredReportWorkSerializer(serializers.Serializer):
    """Serialize one registered report work-page payload."""

    def to_representation(self, post: ResearchhubPost) -> dict[str, Any]:
        """Return feed-like registered report data plus tracker post references."""
        journey = post.journey
        proposal = self.get_proposal(journey)
        grant_post = self.get_grant_post(journey)
        authors = self.serialize_authors(post)

        return {
            "id": post.id,
            "content_type": post._meta.model_name.upper(),
            "content_object": self.serialize_content_object(post, proposal, authors),
            "action_date": post.created_date,
            "action": FeedEntry.PUBLISH,
            "author": self.serialize_author(post),
            "metrics": self.serialize_metrics(post),
            "work": self.serialize_work(post, authors),
            "tracker": [
                self.serialize_tracker_step(
                    JOURNEY_STAGE_GRANT,
                    "Grant",
                    grant_post,
                    is_current=False,
                ),
                self.serialize_tracker_step(
                    JOURNEY_STAGE_PROPOSAL,
                    "Proposal",
                    proposal,
                    is_current=False,
                ),
                self.serialize_tracker_step(
                    JOURNEY_STAGE_REGISTERED_REPORT,
                    "Registered Report",
                    post,
                    is_current=True,
                ),
            ],
            "links": {
                JOURNEY_STAGE_GRANT: self.serialize_tracker_link(grant_post),
                JOURNEY_STAGE_PROPOSAL: self.serialize_tracker_link(proposal),
                JOURNEY_STAGE_REGISTERED_REPORT: self.serialize_tracker_link(post),
            },
        }

    def get_proposal(self, journey: ResearchJourney | None) -> ResearchhubPost | None:
        """Return the proposal attached to the registered report."""
        if journey is None:
            return None
        return JourneyService().get_proposal(journey)

    def get_grant_post(self, journey: ResearchJourney | None) -> ResearchhubPost | None:
        """Return the grant post attached to the registered report journey."""
        if journey is None:
            return None
        return journey.grant_post

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
            "image_url": self.get_image_url(post),
            "unified_document_id": post.unified_document_id,
            "authors": authors,
            "journal_state": "registered_report",
            "proposal": self.serialize_proposal_reference(proposal),
        }

    def serialize_work(
        self, post: ResearchhubPost, authors: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Serialize registered report work data for the work page."""
        full_src = self.get_full_src(post)
        return {
            "id": post.id,
            "authors": authors,
            "created_by": UserSerializer(post.created_by, read_only=True).data,
            "created_date": post.created_date,
            "document_type": post.document_type,
            "doi": post.doi,
            "editor_type": post.editor_type,
            "formatted_html": full_src,
            "full_json": self.get_full_json(post),
            "full_markdown": full_src,
            "full_src": full_src,
            "hubs": SimpleHubSerializer(post.unified_document.hubs, many=True).data,
            "image_url": self.get_image_url(post),
            "is_removed": post.unified_document.is_removed,
            "post_src": self.get_post_src(post),
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
        """Serialize one pizza tracker step and its post reference."""
        return {
            "stage": stage,
            "label": label,
            "exists": post is not None,
            "is_current": is_current,
            "post_id": post.id if post is not None else None,
            "title": post.title if post is not None else None,
            "document_type": post.document_type if post is not None else None,
        }

    def serialize_tracker_link(
        self, post: ResearchhubPost | None
    ) -> dict[str, Any]:
        """Serialize the post reference used for a tracker stage."""
        return {
            "post_id": post.id if post is not None else None,
            "title": post.title if post is not None else None,
        }

    def serialize_proposal_reference(
        self, proposal: ResearchhubPost | None
    ) -> dict[str, Any] | None:
        """Serialize the source proposal reference."""
        if proposal is None:
            return None
        return {
            "id": proposal.id,
            "slug": proposal.slug,
            "title": proposal.title,
            "unified_document_id": proposal.unified_document_id,
        }

    def serialize_authors(self, post: ResearchhubPost) -> list[dict[str, Any]]:
        """Serialize registered report authors."""
        authors = list(post.authors.all())
        if not authors and post.created_by is not None:
            authors = [post.created_by.author_profile]
        return AuthorSerializer(authors, context=self.context, many=True).data

    def serialize_author(self, post: ResearchhubPost) -> dict[str, Any] | None:
        """Serialize the feed author."""
        author = getattr(post.created_by, "author_profile", None)
        if author is None:
            return None
        return SimpleAuthorSerializer(author).data

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

    def get_post_src(self, post: ResearchhubPost) -> str | None:
        """Return the registered report source file URL."""
        try:
            return post.discussion_src.url
        except ValueError:
            return None

    def get_full_src(self, post: ResearchhubPost) -> str | None:
        """Return stored formatted HTML when the report has source content."""
        if not post.discussion_src:
            return None
        try:
            post.discussion_src.open("rb")
            try:
                return post.discussion_src.read().decode("utf-8")
            finally:
                post.discussion_src.close()
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def get_full_json(self, post: ResearchhubPost) -> object | None:
        """Return the notebook JSON used to render the registered report."""
        note = post.note
        if note is None or note.latest_version is None:
            return None

        value = note.latest_version.json
        return parse_note_json(value) or value
