import re
from typing import Any

from rest_framework import serializers

_POST_UPLOAD_KEY = re.compile(r"uploads/posts/users/(\d+)/[^/]+(?:/[^/]+)*")


def is_post_upload_key(key: Any, user_id: int | None = None) -> bool:
    match = _POST_UPLOAD_KEY.fullmatch(key) if isinstance(key, str) else None
    if match is None or ".." in key.split("/"):
        return False
    return user_id is None or match.group(1) == str(user_id)


def validate_post_image_key(
    image: Any, user, *, note=None, existing_image: str | None = None
) -> None:
    if not image or image == existing_image or is_post_upload_key(image, user.id):
        return
    if note is not None and image == note.image and is_post_upload_key(image):
        return
    raise serializers.ValidationError({"image": "Invalid image key."})
