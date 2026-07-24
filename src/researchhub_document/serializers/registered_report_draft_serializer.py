from typing import Any

from rest_framework.serializers import IntegerField, Serializer

from note.serializers import NoteSerializer
from researchhub_document.services.journal_entry_service import RegisteredReportDraft


class RegisteredReportDraftRequestSerializer(Serializer):
    """Validate an editor or moderator registered report draft request."""

    proposal_id = IntegerField()


class RegisteredReportDraftResponseSerializer(NoteSerializer):
    """Serialize a newly created registered report notebook draft."""

    def to_representation(self, draft: RegisteredReportDraft) -> dict[str, Any]:
        """Return the note payload augmented with registered report identifiers."""
        response_data = super().to_representation(draft.note)
        response_data["fundraise_id"] = draft.fundraise.id
        response_data["journey_id"] = draft.journey.id
        response_data["proposal_id"] = draft.proposal.id
        return response_data
