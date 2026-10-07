"""Text extraction and page rendering for files users attach to Research AI chats.

Every supported document reduces to one string: PDF pages via PyMuPDF, each
introduced by a ``[Page N]`` marker the agent can cite; Word documents as
Markdown via mammoth; text formats by decoding. PDF pages also render to images,
and an uploaded image is prepared as one.
"""

import base64
import codecs
import contextlib
import ctypes
import errno
import io
import json
import logging
import math
import os
import pkgutil
import resource
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import fitz
import mammoth
from markdownify import markdownify
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


class UnreadableFileError(ValueError):
    """The file cannot be read; the message is written for the user."""


class ParserSandboxError(RuntimeError):
    """The parsing process could not confine itself, so it parsed nothing."""


@dataclass(frozen=True)
class FileKind:
    extractor: str
    content_type: str
    label: str

    @property
    def is_image(self) -> bool:
        return self.extractor == "image"


PDF = FileKind("pdf", "application/pdf", "PDF")
DOCX = FileKind(
    "docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "Word document",
)
_MARKDOWN = FileKind("text", "text/markdown", "Markdown file")
_JPEG = FileKind("image", "image/jpeg", "JPEG image")
KINDS_BY_EXTENSION = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".txt": FileKind("text", "text/plain", "text file"),
    ".md": _MARKDOWN,
    ".markdown": _MARKDOWN,
    ".csv": FileKind("text", "text/csv", "CSV file"),
    ".tsv": FileKind("text", "text/tab-separated-values", "TSV file"),
    ".tex": FileKind("text", "application/x-tex", "LaTeX file"),
    ".png": FileKind("image", "image/png", "PNG image"),
    ".jpg": _JPEG,
    ".jpeg": _JPEG,
    ".gif": FileKind("image", "image/gif", "GIF image"),
    ".webp": FileKind("image", "image/webp", "WebP image"),
}
_KINDS_BY_CONTENT_TYPE = {
    kind.content_type: kind for kind in KINDS_BY_EXTENSION.values()
}
SUPPORTED_EXTENSIONS = tuple(KINDS_BY_EXTENSION)

# Written under the ``[Page N]`` marker of a page with content but no text.
NO_TEXT_LAYER = "[This page has no text layer; it may be a scan or a figure.]"
# Written after the little text a page has when an image covers most of it.
IMAGE_UNREAD = "[Most of this page is an image; any text in it was not read.]"
OCR_NOTE = "[Text on this page was read by OCR and may contain errors.]"
# Written above the text OCR read in an uploaded image.
IMAGE_OCR_NOTE = "[Text in this image was read by OCR and may contain errors.]"

# A scan under a download stamp or page number: little text over a large image.
_SCAN_MAX_TEXT_CHARS = 500
_SCAN_MIN_IMAGE_COVERAGE = 0.5

# Bounds on work an adversarial file can demand, beyond the upload size cap.
_MAX_PDF_PAGES = 2000
_MAX_DOCX_XML_BYTES = 64 * 1024 * 1024
# A compressed PDF page or a tree of millions of tiny XML elements costs far
# more than the file's size before any text cap applies, so PDF and Word files
# are parsed in a child process under these limits.
_CHILD_CPU_SECONDS = 60
_CHILD_MEMORY_BYTES = 1024 * 1024 * 1024
_CHILD_TIMEOUT_SECONDS = 120
# The most a child may hand back: several times the largest text or image.
_CHILD_OUTPUT_BYTES = 16 * 1024 * 1024
_NO_SANDBOX_EXIT_CODE = 3

# All the child may ask of the kernel once it holds the file: use of the
# descriptors and memory it has, and exit. No files, sockets or processes.
_SANDBOX_SYSCALLS = (
    "read",
    "write",
    "writev",
    "close",
    "fstat",
    "lseek",
    "mmap",
    "munmap",
    "mremap",
    "mprotect",
    "madvise",
    "brk",
    "futex",
    "rt_sigaction",
    "rt_sigprocmask",
    "rt_sigreturn",
    "sigaltstack",
    "clock_gettime",
    "gettimeofday",
    "getrandom",
    "getpid",
    "gettid",
    "restart_syscall",
    "exit",
    "exit_group",
)
# Text encodings the parsers look up by name, which loads a module on first use.
_SANDBOX_CODECS = (
    "ascii",
    "latin-1",
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "raw_unicode_escape",
    "unicode_escape",
    "cp437",
    "cp1252",
)
_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO = 0x00050000
_SCMP_FLTATR_CTL_TSYNC = 4

# Claude rejects images over 2000 px a side once a request carries more than 20.
MAX_IMAGE_EDGE_PX = 2000
# Hard ceiling for any render: an RGB pixmap this size is 48 MB in the child.
_MAX_RENDER_EDGE_PX = 4000
_MIN_RENDER_EDGE_PX = 256
_JPEG_QUALITY = 85
# A render over its byte limit is redone smaller. Bytes go roughly with pixel
# count, so a side shrinks by the square root of the excess, less this margin.
_FIT_MARGIN = 0.95
# One step at most halves a side, however far over the limit the render is.
_FIT_MIN_STEP = 0.5
_IMAGE_MEDIA_TYPES = {"jpeg": "image/jpeg", "png": "image/png"}

# What an upload may hold, whichever of the image extensions it came with.
_UPLOAD_IMAGE_FORMATS = ("JPEG", "PNG", "GIF", "WEBP")
# Pixels the child decodes at most: with transparency, 256 MB of its memory.
_MAX_UPLOAD_IMAGE_PIXELS = 64_000_000

# Text for the PDF pages it is called with (1-based); pages it omits stay marked.
PageRecovery = Callable[[Sequence[int]], Mapping[int, str]]


@dataclass(frozen=True)
class ExtractedText:
    # For a PDF of scans that nothing read, only the page markers and their
    # notes; empty for an image nothing was read in.
    text: str
    page_count: int | None
    truncated: bool
    # 1-based PDF pages left unread: marked ``NO_TEXT_LAYER`` or ``IMAGE_UNREAD``.
    pages_without_text: tuple[int, ...] = ()
    # 1-based PDF pages whose text came from ``recover_pages``.
    ocr_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class PageImage:
    page: int
    data: bytes
    media_type: str
    width: int
    height: int


def resolve_kind(filename: str, content_type: str = "") -> FileKind | None:
    """The kind a file uploads as: by extension, else by its declared MIME type."""
    extension = os.path.splitext(filename)[1].lower()
    if extension:
        return KINDS_BY_EXTENSION.get(extension)
    return kind_for_content_type(content_type.split(";")[0].strip().lower())


def kind_for_content_type(content_type: str) -> FileKind | None:
    return _KINDS_BY_CONTENT_TYPE.get(content_type)


def is_image_type(content_type: str) -> bool:
    """Whether a file stored with this type is an image the user uploaded."""
    kind = kind_for_content_type(content_type)
    return kind is not None and kind.is_image


def extract_text(
    data: bytes,
    kind: FileKind,
    *,
    max_chars: int,
    recover_pages: PageRecovery | None = None,
) -> ExtractedText:
    """Text of the document, cut at ``max_chars``. Raises ``UnreadableFileError``.

    ``recover_pages`` supplies text for PDF pages that have no text layer or
    are mostly an image. An uploaded image goes through ``prepare_image``.
    """
    pages_without_text: tuple[int, ...] = ()
    ocr_pages: tuple[int, ...] = ()
    if kind.extractor == "text":
        text, page_count, truncated = _plain_text(data), None, False
    elif kind.extractor == "pdf":
        output = _run_child("pdf", data, label=kind.label, max_chars=max_chars)
        page_count, truncated = output["page_count"], output["truncated"]
        text, pages_without_text, ocr_pages = _assemble_pdf(
            output["pages"], output["mostly_image"], recover_pages
        )
    else:
        output = _run_child(kind.extractor, data, label=kind.label, max_chars=max_chars)
        text, page_count, truncated = output["text"], None, output["truncated"]
    # Postgres text columns cannot hold NUL.
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text, truncated = text[:max_chars], True
    # An empty Word table still renders its Markdown frame; a PDF of unread
    # scans passes on its page markers.
    if not any(map(str.isalnum, text)):
        raise UnreadableFileError("No readable text was found in this file.")
    return ExtractedText(
        text=text,
        page_count=page_count,
        truncated=truncated,
        pages_without_text=pages_without_text,
        ocr_pages=ocr_pages,
    )


def render_pdf_page(
    data: bytes,
    page: int,
    *,
    dpi: int = 150,
    max_edge_px: int = MAX_IMAGE_EDGE_PX,
    image_format: str = "jpeg",
    max_bytes: int = 3 * 1024 * 1024,
    timeout_seconds: float | None = None,
) -> PageImage:
    """PDF page ``page`` (1-based) as an image. Raises ``UnreadableFileError``.

    Neither side exceeds ``max_edge_px``; the image is scaled down further
    until it fits ``max_bytes``. ``timeout_seconds`` shortens the time allowed.
    """
    if image_format not in _IMAGE_MEDIA_TYPES:
        raise ValueError(f"unsupported image format: {image_format!r}")
    if page < 1 or dpi < 1 or max_edge_px < 1 or max_bytes < 1:
        raise ValueError("page, dpi, max_edge_px and max_bytes must be positive")
    output = _run_child(
        "render",
        data,
        label=PDF.label,
        timeout=timeout_seconds,
        page=page,
        dpi=dpi,
        max_edge_px=min(max_edge_px, _MAX_RENDER_EDGE_PX),
        image_format=image_format,
        max_bytes=max_bytes,
    )
    return PageImage(
        page=page,
        data=base64.b64decode(output["image"]),
        media_type=_IMAGE_MEDIA_TYPES[image_format],
        width=output["width"],
        height=output["height"],
    )


def prepare_image(
    data: bytes,
    *,
    max_edge_px: int = MAX_IMAGE_EDGE_PX,
    max_bytes: int = 3 * 1024 * 1024,
    timeout_seconds: float | None = None,
) -> PageImage:
    """An uploaded image as a JPEG to show a model. Raises ``UnreadableFileError``.

    Upright, transparency over white, and scaled down to fit ``max_edge_px``
    and ``max_bytes``; an animation gives its first frame.
    """
    output = _run_child(
        "image",
        data,
        label="image",
        timeout=timeout_seconds,
        max_edge_px=min(max_edge_px, _MAX_RENDER_EDGE_PX),
        max_bytes=max_bytes,
    )
    return PageImage(
        page=1,
        data=base64.b64decode(output["image"]),
        media_type=_IMAGE_MEDIA_TYPES["jpeg"],
        width=output["width"],
        height=output["height"],
    )


def _assemble_pdf(
    pages: list[str | None],
    mostly_image: list[int],
    recover_pages: PageRecovery | None,
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """Join page texts under their markers.

    ``None`` is a page with no text layer; ``mostly_image`` lists the 1-based
    pages whose little text sits on a large image.
    """
    unread = sorted(
        {number for number, text in enumerate(pages, start=1) if text is None}
        | set(mostly_image)
    )
    # A scan or figure can still be looked at as a page image; blank pages cannot.
    if not unread and not any(pages):
        raise UnreadableFileError(
            "This PDF has no content; all of its pages are blank."
        )
    recovered: dict[int, str] = {}
    if unread and recover_pages is not None:
        for number, text in recover_pages(unread).items():
            if number in unread and text and text.strip():
                recovered[number] = text.strip()
    parts = []
    for number, text in enumerate(pages, start=1):
        if number in recovered:
            text = f"{OCR_NOTE}\n{recovered[number]}"
        elif text is None:
            text = NO_TEXT_LAYER
        elif number in unread:
            text = f"{text}\n{IMAGE_UNREAD}"
        parts.append(f"[Page {number}]\n{text}")
    return (
        "\n\n".join(parts),
        tuple(number for number in unread if number not in recovered),
        tuple(sorted(recovered)),
    )


def _run_child(
    mode: str, data: bytes, *, label: str, timeout: float | None = None, **options
) -> dict:
    too_complex = UnreadableFileError(f"This {label} is too complex to read.")
    if timeout is None or timeout > _CHILD_TIMEOUT_SECONDS:
        timeout = _CHILD_TIMEOUT_SECONDS
    # A file, not a pipe: the child's file size limit bounds what it writes.
    with tempfile.TemporaryFile() as stdout:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    os.path.abspath(__file__),
                    mode,
                    str(_CHILD_CPU_SECONDS),
                    str(_CHILD_MEMORY_BYTES),
                    str(_CHILD_OUTPUT_BYTES),
                    json.dumps(options),
                ],
                input=data,
                stdout=stdout,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                # None of the worker's secrets reach the process that parses.
                env={},
            )
        except subprocess.TimeoutExpired as exc:
            raise too_complex from exc
        stdout.seek(0)
        written = stdout.read(_CHILD_OUTPUT_BYTES)
    if result.returncode == _NO_SANDBOX_EXIT_CODE:
        raise ParserSandboxError(
            f"the file parser could not confine itself: {written[:500]!r}"
        )
    if result.returncode != 0:
        raise too_complex
    output = json.loads(written)
    if "refused" in output:
        # Its result may differ from an unconfined read, so it is not used.
        refused = str(output["refused"])[:200]
        logger.warning("the sandbox kept the file parser from %r", refused)
        raise too_complex
    if "error" in output:
        raise UnreadableFileError(output["error"])
    return output


# no cover: start
# Down to the stop marker runs only in the child, which gets no environment
# to start coverage from and, confined, no file to report to.
def _child_main(
    mode: str, cpu_seconds: int, memory_bytes: int, output_bytes: int, options: dict
) -> None:
    """Child-process entry point: file on stdin, JSON result on stdout."""
    # MuPDF prints its errors to stdout; route them to stderr, off the result.
    result = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))
    # macOS rejects address-space limits; Linux workers enforce them.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    work = {
        "pdf": _pdf_pages,
        "docx": _docx_text,
        "render": _pdf_page_image,
        "image": _upload_image,
    }[mode]
    data = sys.stdin.buffer.read()
    refused: Callable[[], list[str]] = list
    # macOS has no seccomp; Linux workers parse nothing outside the sandbox.
    if sys.platform == "linux":
        try:
            refused = _lock_down(_rehearsal(mode, work, options))
        except Exception as exc:
            with result:
                json.dump({"sandbox": repr(exc)[:300]}, result)
            sys.exit(_NO_SANDBOX_EXIT_CODE)
    try:
        output = work(data, **options)
    except UnreadableFileError as exc:
        output = {"error": str(exc)}
    if modules := refused():
        output = {"refused": f"importing {', '.join(modules)}"}
    with result:
        json.dump(output, result)


def _lock_down(
    rehearse: Callable[[], object],
) -> Callable[[], list[str]]:
    """Leave this process only ``_SANDBOX_SYSCALLS``, for good.

    ``rehearse`` runs before, loading what the work imports on first use, and
    again after; raises unless it then gives the same result. Returns a call
    that lists the installed modules the sandbox has since kept from loading.
    """
    expected = rehearse()
    for name in _SANDBOX_CODECS:
        codecs.lookup(name)
    installed = sys.stdlib_module_names | {
        module.name for module in pkgutil.iter_modules()
    }
    seccomp = ctypes.CDLL("libseccomp.so.2")
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_attr_set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint64]
    seccomp.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    # Any other syscall fails with EPERM, in every thread.
    context = seccomp.seccomp_init(ctypes.c_uint32(_SCMP_ACT_ERRNO | errno.EPERM))
    if not context:
        raise OSError("seccomp_init failed")
    failed = seccomp.seccomp_attr_set(context, _SCMP_FLTATR_CTL_TSYNC, 1)
    for name in _SANDBOX_SYSCALLS:
        number = seccomp.seccomp_syscall_resolve_name(name.encode())
        # Negative where this architecture has no such syscall.
        if number >= 0:
            failed = failed or seccomp.seccomp_rule_add_array(
                context, _SCMP_ACT_ALLOW, number, 0, None
            )
    if failed or seccomp.seccomp_load(context):
        raise OSError("the seccomp filter could not be loaded")
    asked: list[str] = []
    sys.addaudithook(lambda event, args: event == "import" and asked.append(args[0]))
    if rehearse() != expected:
        raise OSError("parsing gives another result inside the sandbox")
    return lambda: sorted(
        {
            name
            for name in asked
            if name.partition(".")[0] in installed and name not in sys.modules
        }
    )


def _rehearsal(mode: str, work: Callable, options: dict) -> Callable[[], object]:
    """``work`` on small files of ``mode``'s kind, made here."""
    if mode == "image":
        samples = [
            _sample_image(image_format) for image_format in _UPLOAD_IMAGE_FORMATS
        ]
        sample_options = {"max_edge_px": _MIN_RENDER_EDGE_PX, "max_bytes": 1024 * 1024}
    elif mode == "docx":
        samples, sample_options = [_sample_docx()], {"max_chars": 1000}
    else:
        document = fitz.open()
        document.new_page().insert_text((72, 72), "A page of text")
        scan = document.new_page()
        scan.insert_image(scan.rect, stream=_sample_image("PNG"))
        # A page count above what the file holds, which ``_open_pdf`` lowers.
        pages = document.xref_get_key(document.pdf_catalog(), "Pages")[1]
        document.xref_set_key(int(pages.split()[0]), "Count", "1000")
        samples, sample_options = [document.tobytes()], {"max_chars": 1000}
        if mode == "render":
            sample_options = {
                "page": 2,
                "dpi": 72,
                "max_edge_px": _MIN_RENDER_EDGE_PX,
                "image_format": options["image_format"],
                "max_bytes": 1024 * 1024,
            }
    return lambda: [work(sample, **sample_options) for sample in samples]


def _sample_image(image_format: str) -> bytes:
    """A small image that its EXIF data, where it keeps any, turns on its side."""
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    Image.new("RGBA" if image_format == "PNG" else "RGB", (32, 16), "navy").save(
        buffer, image_format, exif=exif
    )
    return buffer.getvalue()


def _sample_docx() -> bytes:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    cell = "<w:p><w:r><w:t>A cell</w:t></w:r></w:p>"
    document = (
        f'<w:document xmlns:w="{namespace}"><w:body>'
        f"<w:p><w:r><w:t>A paragraph</w:t></w:r></w:p>"
        f"<w:tbl><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _open_pdf(data: bytes) -> fitz.Document:
    not_a_pdf = UnreadableFileError("This file could not be read as a PDF.")
    # MuPDF "repairs" arbitrary bytes into an empty document rather than fail;
    # the spec puts the header within the first 1024 bytes.
    if b"%PDF-" not in data[:1024]:
        raise not_a_pdf
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - MuPDF raises several types
        raise not_a_pdf from exc
    if document.needs_pass:
        document.close()
        raise UnreadableFileError(
            "This PDF is password-protected. Remove the password and upload it again."
        )
    if document.page_count == 0:
        document.close()
        raise not_a_pdf
    # MuPDF sizes its page map by the declared /Count. Every page is an object
    # of its own, so a count above the object count is lowered to it.
    objects = document.xref_length()
    if document.page_count > objects:
        try:
            pages = document.xref_get_key(document.pdf_catalog(), "Pages")[1]
            document.xref_set_key(int(pages.split()[0]), "Count", str(objects))
        except Exception as exc:  # no page tree whose count can be lowered
            document.close()
            raise not_a_pdf from exc
    return document


def _loadable_page_count(document: fitz.Document, loaded: int) -> int:
    """How many pages load in sequence, given that the first ``loaded`` did.

    Guards against a /Count above the pages that exist. Pages past a lower
    /Count stay out: MuPDF, which also renders the pages, does not load them.
    """
    count = loaded
    while count < document.page_count:
        try:
            document.load_page(count)
        except Exception:  # the page tree ends here, whatever /Count says
            break
        count += 1
    return count


def _pdf_pages(data: bytes, max_chars: int) -> dict:
    """Each page's text; ``None`` for a page with content but no text layer.

    ``mostly_image`` lists the 1-based pages that have a little text over a
    large image, as a scan under a stamp does.
    """
    with _open_pdf(data) as document:
        pages: list[str | None] = []
        mostly_image: list[int] = []
        # No more than max_chars reaches the unlimited parent.
        remaining = max_chars
        cut = False
        try:
            for number, page in enumerate(document, start=1):
                if remaining <= 0 or number > _MAX_PDF_PAGES:
                    # This page exists and is left unread.
                    cut = True
                    break
                page_text = page.get_text().strip()
                # Judged on the page's whole text, before any cut.
                if _text_over_a_scan(page, page_text):
                    mostly_image.append(number)
                if len(page_text) > remaining:
                    page_text, cut = page_text[:remaining], True
                remaining -= len(page_text)
                # A page that draws something yet has no text is a scan or figure.
                if not page_text and page.read_contents().strip():
                    pages.append(None)
                else:
                    pages.append(page_text)
        except Exception as exc:  # noqa: BLE001 - a damaged page stream
            raise UnreadableFileError("This PDF could not be read.") from exc
        page_count = _loadable_page_count(document, len(pages))
    return {
        "pages": pages,
        "mostly_image": mostly_image,
        "page_count": page_count,
        "truncated": cut,
    }


def _text_over_a_scan(page: fitz.Page, text: str) -> bool:
    """Whether the page has a little text and images cover most of it."""
    if not 0 < len(text) <= _SCAN_MAX_TEXT_CHARS:
        return False
    page_area = page.rect.get_area()
    try:
        images = page.get_image_info()
    except Exception:  # noqa: BLE001 - a damaged image does not cost the page its text
        return False
    # Strips of one scan add up; overlapping layers only overstate a full page.
    covered = sum(
        min(fitz.Rect(image["bbox"]).get_area(), page_area) for image in images
    )
    return page_area > 0 and covered >= _SCAN_MIN_IMAGE_COVERAGE * page_area


def _pdf_page_image(
    data: bytes,
    page: int,
    dpi: int,
    max_edge_px: int,
    image_format: str,
    max_bytes: int,
) -> dict:
    with _open_pdf(data) as document:
        try:
            pdf_page = document[page - 1]
        except Exception as exc:  # nothing loads there, whatever /Count says
            raise UnreadableFileError(f"This PDF has no page {page}.") from exc
        try:
            longest = max(pdf_page.rect.width, pdf_page.rect.height)
            if longest <= 0:
                raise ValueError("empty page")
            scale = min(dpi / 72, max_edge_px / longest)
            while True:
                pixmap = pdf_page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                if image_format == "jpeg":
                    image = pixmap.tobytes("jpeg", jpg_quality=_JPEG_QUALITY)
                else:
                    image = pixmap.tobytes("png")
                small = max(pixmap.width, pixmap.height) <= _MIN_RENDER_EDGE_PX
                if len(image) <= max_bytes or small:
                    break
                scale *= _fit_step(len(image), max_bytes)
        except Exception as exc:  # noqa: BLE001 - a damaged page stream
            raise UnreadableFileError("This PDF page could not be rendered.") from exc
    if len(image) > max_bytes:
        raise UnreadableFileError("This PDF page is too detailed to render.")
    return {
        "image": base64.b64encode(image).decode("ascii"),
        "width": pixmap.width,
        "height": pixmap.height,
    }


def _fit_step(size: int, max_bytes: int) -> float:
    """What to scale a side by so an image of ``size`` bytes nears ``max_bytes``."""
    return max(math.sqrt(max_bytes / size) * _FIT_MARGIN, _FIT_MIN_STEP)


def _upload_image(data: bytes, max_edge_px: int, max_bytes: int) -> dict:
    not_an_image = UnreadableFileError("This file could not be read as an image.")
    # Checked below instead, once a JPEG is set to decode at a fraction of its size.
    Image.MAX_IMAGE_PIXELS = None
    try:
        source = Image.open(io.BytesIO(data), formats=_UPLOAD_IMAGE_FORMATS)
        source.draft("RGB", (max_edge_px, max_edge_px))
    except Exception as exc:  # whatever Pillow raises for bytes it cannot identify
        raise not_an_image from exc
    if source.width * source.height > _MAX_UPLOAD_IMAGE_PIXELS:
        raise UnreadableFileError(
            "This image is too large to read. Upload a smaller copy of it."
        )
    try:
        image = _upright_rgb(source, max_edge_px)
        while True:
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=_JPEG_QUALITY)
            encoded = buffer.getvalue()
            small = max(image.size) <= _MIN_RENDER_EDGE_PX
            if len(encoded) <= max_bytes or small:
                break
            step = _fit_step(len(encoded), max_bytes)
            image = image.resize(
                (max(1, round(image.width * step)), max(1, round(image.height * step))),
                Image.Resampling.LANCZOS,
            )
    except MemoryError:
        raise
    except Exception as exc:  # a damaged or cut-short file fails as it is decoded
        raise not_an_image from exc
    if len(encoded) > max_bytes:
        raise UnreadableFileError("This image is too detailed to read.")
    return {
        "image": base64.b64encode(encoded).decode("ascii"),
        "width": image.width,
        "height": image.height,
    }


def _upright_rgb(image: Image.Image, max_edge_px: int) -> Image.Image:
    """The image's first frame, upright, opaque and within ``max_edge_px`` a side."""
    if image.mode == "I;16":
        # 16-bit greys are scaled to 8 bits; a plain conversion clips them to white.
        image = image.point(lambda value: value * (1 / 257)).convert("L")
    elif image.has_transparency_data:
        image = image.convert("RGBA")
    elif image.mode not in ("L", "RGB"):
        # Palette images only scale by nearest neighbour.
        image = image.convert("RGB")
    image.thumbnail((max_edge_px, max_edge_px), Image.Resampling.LANCZOS)
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGBA":
        return image.convert("RGB")
    # A JPEG has no transparency; left to a plain conversion it turns black.
    opaque = Image.new("RGB", image.size, "white")
    opaque.paste(image, mask=image.getchannel("A"))
    return opaque


def _docx_text(data: bytes, max_chars: int) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml_bytes = sum(
                info.file_size
                for info in archive.infolist()
                if info.filename.endswith((".xml", ".rels"))
            )
        if xml_bytes > _MAX_DOCX_XML_BYTES:
            raise UnreadableFileError("This Word document is too large to read.")
        html = mammoth.convert_to_html(
            io.BytesIO(data),
            include_embedded_style_map=False,
            # Images carry no text; leaving them unopened also skips their bytes.
            convert_image=lambda image: [],
        ).value
        text = markdownify(
            html,
            heading_style="ATX",
            table_infer_header=True,
            # The agent reads this text rather than rendering it.
            escape_asterisks=False,
            escape_underscores=False,
        ).strip()
    except (UnreadableFileError, MemoryError):
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt files raise many types
        raise UnreadableFileError(
            "This file could not be read as a Word document (.docx)."
        ) from exc
    # Cut here so no more than max_chars reaches the unlimited parent.
    return {"text": text[:max_chars], "truncated": len(text) > max_chars}


# no cover: stop


def _plain_text(data: bytes) -> str:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = data.decode("utf-16", errors="replace")
    elif b"\x00" in data:
        raise UnreadableFileError("This file does not contain plain text.")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


if __name__ == "__main__":  # pragma: no cover
    _child_main(sys.argv[1], *map(int, sys.argv[2:5]), json.loads(sys.argv[5]))
