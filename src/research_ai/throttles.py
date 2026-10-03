from rest_framework.throttling import UserRateThrottle


class AgentFileCreateThrottle(UserRateThrottle):
    """Each upload a user starts can cost one stored object and one extraction."""

    scope = "research_ai_file_create"
    rate = "60/hour"


class AgentFileCompleteThrottle(UserRateThrottle):
    """Looser than creation: clients retry completion until the object lands."""

    scope = "research_ai_file_complete"
    rate = "300/hour"
