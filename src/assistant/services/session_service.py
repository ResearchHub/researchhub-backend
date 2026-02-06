import logging
from typing import Optional
from uuid import UUID

from django.core.cache import cache

from assistant.models import AssistantSession

logger = logging.getLogger(__name__)

# Cache key prefix for session data
CACHE_KEY_PREFIX = "assistant_session:"
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


class SessionService:
    """
    Service for managing assistant sessions.

    Handles session creation, retrieval, and caching for performance.
    """

    @staticmethod
    def get_or_create_session(
        user,
        session_id: Optional[UUID] = None,
        role: Optional[str] = None,
    ) -> tuple[AssistantSession, bool]:
        """
        Get an existing session or create a new one.

        Args:
            user: The authenticated user
            session_id: Optional existing session ID
            role: Required for new sessions ("researcher" or "funder")

        Returns:
            Tuple of (session, created)

        Raises:
            ValueError: If role is missing for a new session
            AssistantSession.DoesNotExist: If session_id is invalid
        """
        if session_id:
            # Try to get existing session
            session = SessionService.get_session(session_id, user)
            if session:
                return session, False

        # Create new session
        if not role:
            raise ValueError("Role is required when creating a new session")

        if role not in [AssistantSession.RESEARCHER, AssistantSession.FUNDER]:
            raise ValueError(f"Invalid role: {role}")

        session = AssistantSession(
            user=user,
            role=role,
        )
        session.initialize_field_state()
        session.save()

        logger.info(f"Created new assistant session {session.id} for user {user.id}")
        return session, True

    @staticmethod
    def get_session(session_id: UUID, user) -> Optional[AssistantSession]:
        """
        Get a session by ID, validating ownership.

        Args:
            session_id: The session UUID
            user: The user who must own the session

        Returns:
            AssistantSession or None if not found/unauthorized
        """
        # Try cache first
        cache_key = f"{CACHE_KEY_PREFIX}{session_id}"
        cached_session_data = cache.get(cache_key)

        if cached_session_data:
            # Validate user ownership from cached data
            if cached_session_data.get("user_id") == user.id:
                try:
                    session = AssistantSession.objects.get(id=session_id)
                    return session
                except AssistantSession.DoesNotExist:
                    cache.delete(cache_key)
                    return None

        # Fetch from database
        try:
            session = AssistantSession.objects.get(id=session_id, user=user)

            # Cache session metadata
            SessionService._cache_session(session)

            return session
        except AssistantSession.DoesNotExist:
            logger.warning(
                f"Session {session_id} not found or unauthorized for user {user.id}"
            )
            return None

    @staticmethod
    def _cache_session(session: AssistantSession) -> None:
        """Cache session metadata for quick access."""
        cache_key = f"{CACHE_KEY_PREFIX}{session.id}"
        cache.set(
            cache_key,
            {
                "user_id": session.user_id,
                "role": session.role,
                "is_complete": session.is_complete,
            },
            timeout=CACHE_TTL_SECONDS,
        )

    @staticmethod
    def invalidate_cache(session_id: UUID) -> None:
        """Invalidate cached session data."""
        cache_key = f"{CACHE_KEY_PREFIX}{session_id}"
        cache.delete(cache_key)

    @staticmethod
    def get_user_sessions(user, limit: int = 10) -> list[AssistantSession]:
        """
        Get recent sessions for a user.

        Args:
            user: The user
            limit: Maximum number of sessions to return

        Returns:
            List of recent sessions ordered by creation date
        """
        return list(
            AssistantSession.objects.filter(user=user).order_by("-created_date")[:limit]
        )

    @staticmethod
    def delete_session(session_id: UUID, user) -> bool:
        """
        Delete a session.

        Args:
            session_id: The session UUID
            user: The user who must own the session

        Returns:
            True if deleted, False if not found
        """
        try:
            session = AssistantSession.objects.get(id=session_id, user=user)
            session.delete()
            SessionService.invalidate_cache(session_id)
            logger.info(f"Deleted assistant session {session_id}")
            return True
        except AssistantSession.DoesNotExist:
            return False
