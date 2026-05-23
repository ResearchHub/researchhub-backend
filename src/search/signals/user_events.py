from typing import Any

from django.dispatch import receiver

from search.tasks import update_user_related_documents
from user.events import (
    UserReinstatedEvent,
    UserSuspendedEvent,
    user_reinstated,
    user_suspended,
)


@receiver(user_suspended, dispatch_uid="search_user_suspended")
def handle_user_suspended(
    sender: Any, event: UserSuspendedEvent, **kwargs: Any
) -> None:
    update_user_related_documents.delay(event.user_id)


@receiver(user_reinstated, dispatch_uid="search_user_reinstated")
def handle_user_reinstated(
    sender: Any, event: UserReinstatedEvent, **kwargs: Any
) -> None:
    update_user_related_documents.delay(event.user_id)
