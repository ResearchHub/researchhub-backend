from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from invite.models import NoteInvitation
from researchhub_access_group.models import Permission
from user.constants.gatekeeper_constants import ELN
from user.models import Gatekeeper


class NoteInvitationError(Exception):
    """
    Base exception for note invitation errors.
    """


class NoteInvitationExpiredError(NoteInvitationError):
    """
    Raised when an invitation has expired.
    """


class NoteInvitationRecipientMismatchError(NoteInvitationError):
    """
    Raised when an invitation recipient doesn't match the user accepting the invite.
    """


class NoteInvitationService:
    """
    Service for handling note invitations.
    """

    def get_active_invite(
        self, key: str, *, for_update: bool = False
    ) -> NoteInvitation:
        """
        Get an active note invitation.

        Args:
            key: The unique key of the invitation.
            for_update: Whether to lock the invitation until the current transaction
                completes.
        Raises:
            NoteInvitationExpiredError: If the invitation has expired
                or has already been accepted.
        """
        invitations = NoteInvitation.objects
        if for_update:
            invitations = invitations.select_for_update()

        invite = invitations.get(key=key)

        if invite.is_expired() or invite.accepted:
            raise NoteInvitationExpiredError

        return invite

    @transaction.atomic
    def accept_invite(self, key: str, user) -> NoteInvitation:
        """
        Accept a note invitation.

        Args:
            key: The unique key of the invitation.
            user: The user accepting the invitation.
        Returns:
            NoteInvitation: The accepted invitation.
        Raises:
            NoteInvitationExpiredError: If the invitation has expired
                or has already been accepted.
            NoteInvitationRecipientMismatchError: If the invitation recipient doesn't
                match the user.
        """
        invite = self.get_active_invite(key, for_update=True)

        if invite.recipient and user != invite.recipient:
            raise NoteInvitationRecipientMismatchError

        if not invite.recipient:
            self._claim_recipientless_invite(invite, user)

        note = invite.note
        invite_type = invite.invite_type
        unified_document = note.unified_document
        permissions = note.unified_document.permissions
        content_type = ContentType.objects.get_for_model(unified_document)

        if not permissions.filter(user=user).exists():
            Permission.objects.create(
                access_type=invite_type,
                content_type=content_type,
                object_id=unified_document.id,
                user=user,
            )

        Gatekeeper.objects.get_or_create(
            user=user,
            type=ELN,
            defaults={"email": invite.recipient_email},
        )
        invite.accept()

        return invite

    def _claim_recipientless_invite(self, invite: NoteInvitation, user) -> None:
        """
        Claim a recipientless invite for an authenticated user.

        Args:
            invite: The note invitation to claim.
            user: The user claiming the invitation.
        Raises:
            NoteInvitationRecipientMismatchError: If the user isn't authenticated.
        """
        if not getattr(user, "is_authenticated", False):
            raise NoteInvitationRecipientMismatchError

        invite.recipient = user
