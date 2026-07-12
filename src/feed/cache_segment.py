from rest_framework.request import Request

from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


def get_feed_cache_segment(request: Request) -> tuple[str | None, bool]:
    """Return (suffix, should_cache) for grant/funding feed page caching.

    suffix is ``:public``, ``:viewer-{user_id}``, or ``None`` when caching is
    disabled (moderators and hub editors always get a fresh response).
    """
    user = request.user

    if user.is_authenticated and (
        getattr(user, "moderator", False) or user.is_hub_editor()
    ):
        return None, False

    if not user.is_authenticated:
        return ":public", True

    has_private_visibility = (
        ResearchhubPost.objects.visible_to(user)
        .filter(
            unified_document__is_public=False,
            unified_document__is_removed=False,
        )
        .exists()
    )

    if has_private_visibility:
        return f":viewer-{user.id}", True

    return ":public", True
