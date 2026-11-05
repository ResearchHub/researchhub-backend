import hashlib

from oauth2_provider.models import get_access_token_model


class OAuthIntrospectionService:
    """
    Describes access tokens for token introspection (RFC 7662).
    """

    def introspect(self, token_value: str) -> dict:
        """
        Returns the introspection response for an access token.
        """
        checksum = hashlib.sha256(token_value.encode()).hexdigest()
        token = (
            get_access_token_model()
            .objects.select_related("user", "application")
            .filter(token_checksum=checksum)
            .first()
        )
        if token is None or not token.is_valid():
            return {"active": False}
        # Only accept tokens of active users:
        if token.user is None or not token.user.is_active:
            return {"active": False}

        response = {
            "active": True,
            "sub": str(token.user.id),
            "client_id": token.application.client_id,
            "scope": token.scope,
            "exp": int(token.expires.timestamp()),
        }
        if token.resource:
            response["aud"] = token.resource
        return response
