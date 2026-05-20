from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.dispatch import Signal


@dataclass(frozen=True)
class UserSuspendedEvent:
    user_id: int


@dataclass(frozen=True)
class UserReinstatedEvent:
    user_id: int


user_suspended: Signal = Signal()
user_reinstated: Signal = Signal()


def publish_user_suspended(*, sender: Any, user_id: int) -> None:
    """
    Publish a user suspended event.

    This function is transaction-aware and will send the signal after the current
    transaction commits successfully.

        Args:
            sender: The sender of the signal, typically the model class.
            user_id: The ID of the user who was suspended.
    """
    event = UserSuspendedEvent(user_id=user_id)
    transaction.on_commit(
        lambda: user_suspended.send(
            sender=sender,
            event=event,
        )
    )


def publish_user_reinstated(*, sender: Any, user_id: int) -> None:
    """
    Publish a user reinstated event.

    This function is transaction-aware and will send the signal after the current
    transaction commits successfully.

        Args:
            sender: The sender of the signal, typically the model class.
            user_id: The ID of the user who was reinstated.
    """
    event = UserReinstatedEvent(user_id=user_id)
    transaction.on_commit(
        lambda: user_reinstated.send(
            sender=sender,
            event=event,
        )
    )
