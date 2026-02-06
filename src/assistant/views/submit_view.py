import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.text import slugify
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from assistant.models import AssistantSession
from assistant.serializers import SubmitRequestSerializer, SubmitResponseSerializer
from assistant.services.session_service import SessionService
from hub.models import Hub
from researchhub.settings import TESTING
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from user.related_models.author_model import Author
from utils.sentry import log_error

logger = logging.getLogger(__name__)

MIN_POST_TITLE_LENGTH = 20
MIN_POST_BODY_LENGTH = 50


class SubmitView(APIView):
    """
    API endpoint for submitting the completed assistant session.

    POST /api/assistant/submit/

    Validates the collected fields and creates the appropriate document
    (ResearchhubPost for researchers, Grant for funders).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Submit the completed session payload.

        Request body:
        {
            "session_id": "uuid"
        }

        Response:
        {
            "success": true,
            "message": "Proposal created successfully",
            "document_id": 123,
            "document_type": "post"
        }
        """
        serializer = SubmitRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_id = serializer.validated_data["session_id"]

        # Get the session
        session = SessionService.get_session(session_id, request.user)
        if not session:
            return Response(
                {"error": "Session not found or access denied"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Validate session is complete
        if not session.is_complete:
            return Response(
                {
                    "error": "Session is not complete. Please finish filling all required fields."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate payload exists
        if not session.payload:
            return Response(
                {"error": "No payload found. Please complete the conversation first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if session.role == AssistantSession.RESEARCHER:
                result = self._create_researcher_post(request.user, session.payload)
            else:
                result = self._create_funder_grant(request.user, session.payload)

            # Mark session as submitted (optional: could delete or archive)
            logger.info(f"Session {session_id} submitted successfully")

            response_serializer = SubmitResponseSerializer(data=result)
            if response_serializer.is_valid():
                return Response(
                    response_serializer.data, status=status.HTTP_201_CREATED
                )
            return Response(result, status=status.HTTP_201_CREATED)

        except Exception as e:
            log_error(e, message=f"Failed to submit session {session_id}")
            logger.exception("Submission error")
            return Response(
                {"error": "Failed to create document. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _create_researcher_post(self, user, payload: dict) -> dict:
        """
        Create a ResearchhubPost (preregistration) from the payload.

        Args:
            user: The authenticated user
            payload: The submission payload with title, description, hubs, etc.

        Returns:
            dict with success, message, document_id, document_type
        """
        title = payload.get("title", "")
        renderable_text = payload.get("renderable_text", "")
        full_src = payload.get("full_src", renderable_text)
        document_type = payload.get("document_type", "PREREGISTRATION")
        hub_ids = payload.get("hubs", [])
        author_ids = payload.get("authors", [])

        # Validate title and description
        if len(title) < MIN_POST_TITLE_LENGTH:
            raise ValueError(
                f"Title must be at least {MIN_POST_TITLE_LENGTH} characters"
            )

        if len(renderable_text) < MIN_POST_BODY_LENGTH:
            raise ValueError(
                f"Description must be at least {MIN_POST_BODY_LENGTH} characters"
            )

        with transaction.atomic():
            # Create unified document
            hubs = Hub.objects.filter(id__in=hub_ids)
            unified_document = ResearchhubUnifiedDocument.objects.create(
                document_type=document_type,
            )
            unified_document.hubs.add(*hubs)
            unified_document.save()

            # Create the post
            slug = slugify(title)
            rh_post = ResearchhubPost.objects.create(
                created_by=user,
                document_type=document_type,
                slug=slug,
                editor_type=CK_EDITOR,
                renderable_text=renderable_text,
                title=title,
                unified_document=unified_document,
            )

            # Set authors if provided
            if author_ids:
                authors = Author.objects.filter(id__in=author_ids)
                rh_post.authors.set(authors)

            # Save the source file
            if not TESTING:
                file_name = f"RH-POST-{document_type}-USER-{user.id}.txt"
                full_src_file = ContentFile(full_src.encode())
                if document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                    rh_post.discussion_src.save(file_name, full_src_file)
                else:
                    rh_post.eln_src.save(file_name, full_src_file)

            # Handle optional fundraise
            if fundraise_amount := payload.get("fundraise_goal_amount"):
                self._create_fundraise(
                    user=user,
                    unified_document=unified_document,
                    amount=fundraise_amount,
                    currency=payload.get("fundraise_goal_currency", "USD"),
                )

            logger.info(f"Created ResearchhubPost {rh_post.id} for user {user.id}")

            return {
                "success": True,
                "message": "Proposal created successfully",
                "document_id": rh_post.id,
                "document_type": "post",
            }

    def _create_funder_grant(self, user, payload: dict) -> dict:
        """
        Create a Grant from the payload.

        Note: Grant creation typically requires moderator permissions.
        For POC, we'll create the underlying post and grant together.

        Args:
            user: The authenticated user
            payload: The submission payload

        Returns:
            dict with success, message, document_id, document_type
        """
        from purchase.models import Grant
        from purchase.related_models.constants.currency import USD

        title = payload.get("title", "")
        description = payload.get("description", "")
        amount = payload.get("amount")
        currency = payload.get("currency", USD)
        hub_ids = payload.get("hubs", [])
        end_date = payload.get("end_date")
        contact_ids = payload.get("contact_ids", [])

        if not amount:
            raise ValueError("Funding amount is required")

        with transaction.atomic():
            # Create unified document for the grant
            hubs = Hub.objects.filter(id__in=hub_ids)
            unified_document = ResearchhubUnifiedDocument.objects.create(
                document_type="GRANT",
            )
            unified_document.hubs.add(*hubs)
            unified_document.save()

            # Create the grant
            grant = Grant.objects.create(
                created_by=user,
                unified_document=unified_document,
                amount=amount,
                currency=currency,
                description=f"{title}\n\n{description}" if title else description,
                end_date=end_date,
            )

            # Set contacts if provided
            if contact_ids:
                from user.models import User

                contacts = User.objects.filter(id__in=contact_ids)
                grant.contacts.set(contacts)

            logger.info(f"Created Grant {grant.id} for user {user.id}")

            return {
                "success": True,
                "message": "Funding opportunity created successfully",
                "document_id": grant.id,
                "document_type": "grant",
            }

    def _create_fundraise(self, user, unified_document, amount, currency):
        """Create a fundraise for the preregistration post."""
        from purchase.services.fundraise_service import FundraiseService

        try:
            fundraise_service = FundraiseService()
            fundraise = fundraise_service.create_fundraise_with_escrow(
                user=user,
                unified_document=unified_document,
                goal_amount=amount,
                goal_currency=currency,
            )
            logger.info(
                f"Created Fundraise {fundraise.id} for document {unified_document.id}"
            )
            return fundraise
        except Exception as e:
            logger.warning(f"Failed to create fundraise: {e}")
            # Don't fail the whole submission if fundraise fails
            return None
