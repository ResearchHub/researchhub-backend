"""PDF pages as images the model can look at, rendered on first need and stored.

A page's render lives at one key beside its file's original, so every key a
file can have follows from its ``page_count`` and nothing lists the bucket.
"""

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import partial

from botocore.exceptions import ClientError
from django.conf import settings

from research_ai.models import AgentFile
from research_ai.services.agent.types import ImageBlock
from research_ai.services.agent_files.config import AgentFileConfig
from research_ai.services.agent_files.extraction import PDF, render_pdf_page
from researchhub.services.private_storage_service import PrivateStorageService

logger = logging.getLogger(__name__)

_SETTING_OVERRIDES = {
    "dpi": "RESEARCH_AI_FILE_PAGE_RENDER_DPI",
    "max_edge_px": "RESEARCH_AI_FILE_PAGE_RENDER_MAX_EDGE_PX",
    "max_bytes": "RESEARCH_AI_FILE_PAGE_RENDER_MAX_BYTES",
    "concurrency": "RESEARCH_AI_FILE_PAGE_RENDER_CONCURRENCY",
    "max_seconds": "RESEARCH_AI_FILE_PAGE_RENDER_MAX_SECONDS",
}
_IMAGE_FORMAT = "jpeg"
_MEDIA_TYPE = "image/jpeg"
# A PDF can claim any page count. Text extraction stops at this page too, and
# it bounds the keys a purge deletes.
MAX_PAGE = 2000


@dataclass(frozen=True)
class PageRenderConfig:
    dpi: int = 150

    # Longest side; Claude rejects more once a request carries over 20 images.
    max_edge_px: int = 2000

    # A page is scaled down until it fits; bounds what a message's pages add
    # to a request, which takes 10 MB of images on Bedrock and OpenRouter.
    max_bytes: int = 500 * 1024

    # Pages rendered at once, each in its own child process.
    concurrency: int = 4

    # Wall time for one call; a page not stored by then is reported as failed.
    max_seconds: int = 60

    @classmethod
    def from_settings(cls) -> "PageRenderConfig":
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )


@dataclass(frozen=True)
class RenderedPages:
    # In the order the pages were asked for.
    images: tuple[ImageBlock, ...]
    # Pages asked for that could not be rendered or stored.
    failed: tuple[int, ...] = ()


def page_image_count(file: AgentFile) -> int:
    """How many of the file's pages can be shown as images; only PDFs have any."""
    return min(file.page_count or 0, MAX_PAGE)


def page_image_key(file: AgentFile, page: int) -> str:
    return f"{file.storage_key.rsplit('/', 1)[0]}/pages/{page}.jpg"


def page_image_keys(file: AgentFile) -> list[str]:
    """Every key a render of the file's pages can be stored at."""
    return [page_image_key(file, page) for page in range(1, page_image_count(file) + 1)]


class PageImageService:
    """Images of a READY PDF's pages, rendered and stored on first need.

    Only for a file sent in a live chat: a purge deletes any other with its
    page images. ``storage``, the configs and ``render`` are injectable for tests.
    """

    def __init__(
        self,
        *,
        storage: PrivateStorageService | None = None,
        config: PageRenderConfig | None = None,
        file_config: AgentFileConfig | None = None,
        render: Callable = render_pdf_page,
    ):
        self.storage = PrivateStorageService() if storage is None else storage
        self._config = config
        self._file_config = file_config
        self._render = render

    @property
    def config(self) -> PageRenderConfig:
        return self._config or PageRenderConfig.from_settings()

    def images(self, file: AgentFile, pages: Sequence[int]) -> RenderedPages:
        """Images of ``pages`` (1-based), without those that cannot be rendered.

        Raises ``ValueError`` unless ``file`` is a READY PDF that has every page.
        """
        last = page_image_count(file)
        ready = file.status == AgentFile.Status.READY
        if not ready or file.content_type != PDF.content_type or not last:
            raise ValueError("page images need a READY PDF")
        if not all(isinstance(page, int) and 1 <= page <= last for page in pages):
            raise ValueError(f"pages must be between 1 and {last}")
        # Worker threads get plain values, never the model instance.
        keys = {page: page_image_key(file, page) for page in pages}
        if not _kept(file):
            # A purge may be deleting the file's keys; a page stored now would stay.
            logger.warning("agent file %s is not in a live chat", file.id)
            return RenderedPages(images=(), failed=tuple(keys))
        config = self.config
        deadline = time.monotonic() + config.max_seconds
        executor = ThreadPoolExecutor(max_workers=max(1, config.concurrency))
        try:
            stored = _run(executor, self._is_stored, keys, deadline)
            missing = {page: key for page, key in keys.items() if page not in stored}
            data = self._original(file) if missing else None
            if data is not None:
                store = partial(self._render_and_store, data, config, deadline)
                stored |= _run(executor, store, missing, deadline)
        finally:
            # A page still rendering at the deadline is left behind, not waited for.
            executor.shutdown(wait=False, cancel_futures=True)
        failed = tuple(page for page in keys if page not in stored)
        if failed:
            logger.warning("agent file %s: no image for pages %s", file.id, failed)
        return RenderedPages(
            images=tuple(
                ImageBlock(
                    ref=key,
                    media_type=_MEDIA_TYPE,
                    label=f"{file.filename}, page {page}",
                )
                for page, key in keys.items()
                if page in stored
            ),
            failed=failed,
        )

    def _is_stored(self, page: int, key: str) -> bool:
        try:
            return self.storage.head(key) is not None
        except Exception as error:  # an unconfirmed page is rendered again
            if not _forbidden(error):
                logger.warning("could not check page image %s", key, exc_info=True)
            return False

    def _original(self, file: AgentFile) -> bytes | None:
        """The PDF the file's text was read from; ``None`` when it cannot be read."""
        config = self._file_config or AgentFileConfig.from_settings()
        try:
            return self.storage.read(
                file.storage_key, max_bytes=config.max_file_bytes, if_match=file.etag
            )
        except Exception:  # the caller still gets the pages already stored
            logger.warning("could not read agent file %s", file.id, exc_info=True)
            return None

    def _render_and_store(
        self,
        data: bytes,
        config: PageRenderConfig,
        deadline: float,
        page: int,
        key: str,
    ) -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            image = self._render(
                data,
                page,
                dpi=config.dpi,
                max_edge_px=config.max_edge_px,
                image_format=_IMAGE_FORMAT,
                max_bytes=config.max_bytes,
                timeout_seconds=remaining,
            )
            self.storage.write(key, image.data, content_type=_MEDIA_TYPE)
        except Exception:  # one bad page must not fail the caller
            logger.warning("could not store page image %s", key, exc_info=True)
            return False
        return True


def _run(
    executor: ThreadPoolExecutor,
    work: Callable[[int, str], bool],
    keys: dict[int, str],
    deadline: float,
) -> set[int]:
    """The pages ``work`` returned true for before the deadline."""
    futures = {page: executor.submit(work, page, key) for page, key in keys.items()}
    wait(futures.values(), timeout=max(0, deadline - time.monotonic()))
    return {page for page, future in futures.items() if _succeeded(future)}


def _succeeded(future) -> bool:
    return future.done() and not future.cancelled() and bool(future.result())


def _kept(file: AgentFile) -> bool:
    """Whether no purge deletes the file: sent, owned, and its chat not removed."""
    return AgentFile.objects.filter(
        id=file.id,
        message__isnull=False,
        user__isnull=False,
        conversation__is_removed=False,
    ).exists()


def _forbidden(error: Exception) -> bool:
    """S3's answer for a missing object when the role cannot list the bucket."""
    return (
        isinstance(error, ClientError)
        and error.response.get("Error", {}).get("Code") == "403"
    )
