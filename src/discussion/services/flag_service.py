from django.contrib.admin.options import get_content_type_for_model
from django.db import transaction
from django.db.models import Model

from discussion.models import Flag
from discussion.serializers import FlagSerializer
from user.models import User


def create_flag(
    user: User,
    item: Model,
    reason: str | None,
    reason_choice: str | None,
    reason_memo: str | None = None,
) -> tuple[Flag, dict]:
    """Flag the item on the user's behalf and tag the flag with the item's hubs."""
    with transaction.atomic():
        data = {
            "created_by": user.id,
            "object_id": item.id,
            "content_type": get_content_type_for_model(item).id,
            "reason": reason or reason_choice,
            "reason_choice": reason_choice or reason,
            # Default to empty string to match model default and avoid nulls
            "reason_memo": reason_memo or "",
        }
        serializer = FlagSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        flag = serializer.save()
        flag.hubs.add(*item.unified_document.hubs.all())
        return flag, serializer.data
