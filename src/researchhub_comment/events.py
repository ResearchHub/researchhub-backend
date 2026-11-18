from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.dispatch import Signal


@dataclass(frozen=True)
class CommentSubmittedEvent:
    """A user posted or edited the comment through the comment API."""

    comment_id: int


comment_submitted: Signal = Signal()


def publish_comment_submitted(*, sender: Any, comment_id: int) -> None:
    """Send ``comment_submitted`` once the current transaction commits."""
    event = CommentSubmittedEvent(comment_id=comment_id)
    transaction.on_commit(lambda: comment_submitted.send(sender=sender, event=event))
