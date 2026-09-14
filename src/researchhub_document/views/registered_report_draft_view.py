from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from researchhub_document.serializers.registered_report_draft_serializer import (
    RegisteredReportDraftRequestSerializer,
    RegisteredReportDraftResponseSerializer,
)
from researchhub_document.services.journal_entry_service import (
    JournalEntryService,
    RegisteredReportDraftValidationError,
)
from user.permissions import IsModerator, UserIsEditor


class RegisteredReportDraftView(APIView):
    """Create editor- or moderator-owned registered report notebook drafts."""

    permission_classes = [UserIsEditor | IsModerator]

    def post(self, request: Request) -> Response:
        """Create a registered report notebook draft from an eligible proposal."""
        request_serializer = RegisteredReportDraftRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        try:
            draft = JournalEntryService().create_registered_report_draft(
                request.user,
                request_serializer.validated_data["proposal_id"],
            )
        except RegisteredReportDraftValidationError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = RegisteredReportDraftResponseSerializer(
            draft,
            context={"request": request},
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
