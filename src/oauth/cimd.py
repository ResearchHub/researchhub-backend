from oauth2_provider.cimd import SafeMetadataFetcher
from oauth2_provider.settings import oauth2_settings


class SupportedGrantsMetadataFetcher(SafeMetadataFetcher):
    """
    Fetches CIMD documents like DOT, but keeps only the grant types this server
    supports. DOT rejects documents that list more than one grant type besides
    `refresh_token`, and Claude's also lists the JWT bearer grant.
    """

    def fetch(self, client_id):
        metadata, max_age = super().fetch(client_id)
        grant_types = metadata.get("grant_types")
        if not isinstance(grant_types, list):
            return metadata, max_age

        supported = oauth2_settings.OAUTH2_GRANT_TYPES_SUPPORTED
        metadata = {
            **metadata,
            "grant_types": [g for g in grant_types if g in supported],
        }
        return metadata, max_age
