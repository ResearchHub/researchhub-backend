"""Resolve which ``Expert`` row is a ResearchHub user.

The notebook chat grounds drafting in the researcher profile the expert
pipeline keeps on ``Expert.profile``. Resolution is read-only, strongest
evidence first:

1. ``registered_user`` -- the explicit link the signup matcher records.
2. The invitation chain -- outreach emails hang a ``NoteInvitation`` off
   ``GeneratedEmail.note_invitation``, and accepting one claims it for
   whichever authenticated user clicked the tokenized link. That associates
   the user with the invited expert identity even when they signed up under
   a different email than the one the outreach targeted.
3. The user's account email.
"""

from research_ai.models import Expert, GeneratedEmail
from user.models import User


def expert_for_user(user: User) -> Expert | None:
    """The user's Expert row, or ``None`` when no row matches."""
    expert = Expert.objects.filter(registered_user=user).order_by("id").first()
    if expert is not None:
        return expert
    expert = _invited_expert(user)
    if expert is not None:
        return expert
    email = (user.email or "").strip().lower()
    if not email:
        return None
    return Expert.objects.filter(email__iexact=email).order_by("id").first()


def _invited_expert(user: User) -> Expert | None:
    """The expert identity behind an invitation this user holds, newest first.

    Resolved from the invitation's own ``recipient_email`` -- stamped at
    creation and never editable -- not from ``GeneratedEmail.expert_email``,
    which editors can retarget after the invitation was claimed.
    """
    emails = (
        GeneratedEmail.objects.filter(note_invitation__recipient=user)
        .exclude(note_invitation__recipient_email="")
        .order_by("-created_date")
        .values_list("note_invitation__recipient_email", flat=True)
    )
    seen: set[str] = set()
    for email in emails:
        email = email.strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        expert = Expert.objects.filter(email__iexact=email).order_by("id").first()
        if expert is not None:
            return expert
    return None
