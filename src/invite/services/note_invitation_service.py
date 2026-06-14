from django.contrib.contenttypes.models import ContentType

from invite.models import NoteInvitation
from researchhub_access_group.models import Permission


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

    def get_active_invite(self, key: str) -> NoteInvitation:
        """
        Get an active note invitation.

        Raises:
            NoteInvitationExpiredError: If the invitation has expired
                or has already been accepted.
        """
        invite = NoteInvitation.objects.get(key=key)

        if invite.is_expired() or invite.accepted:
            raise NoteInvitationExpiredError()

        return invite

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
        invite = self.get_active_invite(key)

        if invite.recipient and user != invite.recipient:
            raise NoteInvitationRecipientMismatchError()

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

        invite.accept()

        return invite

    def _claim_recipientless_invite(self, invite: NoteInvitation, user) -> None:
        """
        Claim a recipientless invite for a user if the user's email matches the invite's
        email.

        Args:
            invite: The note invitation to claim.
            user: The user claiming the invitation.
        Raises:
            NoteInvitationRecipientMismatchError: If the user's email doesn't match the
                invite's email.
        """
        user_email = (getattr(user, "email", "") or "").strip().lower()
        invite_email = (invite.recipient_email or "").strip().lower()

        if (
            not getattr(user, "is_authenticated", False)
            or not user_email
            or not invite_email
            or user_email != invite_email
        ):
            raise NoteInvitationRecipientMismatchError()

        invite.recipient = user
