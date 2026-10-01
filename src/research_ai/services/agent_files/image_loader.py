"""Loads the images chat messages refer to from the private bucket."""

from botocore.exceptions import ClientError

from research_ai.services.agent.images import ImageUnavailableError
from researchhub.services.private_storage_service import PrivateStorageService

# Chat files, and anything rendered from them, live under this prefix.
KEY_PREFIX = "uploads/research_ai/"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
# One turn rebuilds its request for every model call; keep its images in memory.
_MAX_CACHED_BYTES = 64 * 1024 * 1024


class PrivateStorageImageLoader:
    """An ``ImageLoader`` whose refs are private-bucket keys.

    Build one per turn: it keeps what it loads. ``storage`` is injectable for
    tests.
    """

    def __init__(
        self,
        *,
        storage: PrivateStorageService | None = None,
        key_prefix: str = KEY_PREFIX,
    ):
        self.storage = PrivateStorageService() if storage is None else storage
        self._key_prefix = key_prefix
        self._cache: dict[str, bytes] = {}
        self._cached_bytes = 0

    def __call__(self, ref: str) -> bytes:
        if ref in self._cache:
            return self._cache[ref]
        # Refs are written by the server, but a key is still never trusted to
        # leave the chat files' prefix.
        if not ref.startswith(self._key_prefix) or ".." in ref:
            raise ImageUnavailableError(ref)
        try:
            data = self.storage.read(ref, max_bytes=_MAX_IMAGE_BYTES)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "NoSuchKey":
                raise
            raise ImageUnavailableError(ref) from error
        except ValueError as error:
            # Over ``max_bytes``: no provider would accept it either.
            raise ImageUnavailableError(ref) from error
        if self._cached_bytes + len(data) <= _MAX_CACHED_BYTES:
            self._cache[ref] = data
            self._cached_bytes += len(data)
        return data
