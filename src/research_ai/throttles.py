from rest_framework.throttling import UserRateThrottle

from utils.throttles import CloudflareClientIPMixin


class AgentFileCreateThrottle(UserRateThrottle):
    """Each upload a user starts can cost one stored object and one extraction."""

    scope = "research_ai_file_create"
    rate = "60/hour"


class AgentFileCompleteThrottle(UserRateThrottle):
    """Looser than creation: clients retry completion until the object lands."""

    scope = "research_ai_file_complete"
    rate = "300/hour"


class SharePostGenerateThrottle(CloudflareClientIPMixin, UserRateThrottle):
    """Anyone can share, so this bounds model calls per user (per IP when anonymous)."""

    scope = "research_ai_share_post_generate"
    rate = "30/hour"


class CoverImageGenerationThrottle(UserRateThrottle):
    """Each request generates several images, each a paid OpenRouter call."""

    scope = "research_ai_cover_image_generation"
    rate = "10/hour"
