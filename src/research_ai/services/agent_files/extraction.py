"""Text extraction and page rendering for files users attach to Research AI chats.

Every supported format reduces to one string: PDF pages via PyMuPDF, each
introduced by a ``[Page N]`` marker the agent can cite; Word documents as
Markdown via mammoth; text formats by decoding. PDF pages also render to images.
"""

import base64
import codecs
import contextlib
import io
import json
import os
import resource
import subprocess
import sys
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import fitz
import mammoth
from markdownify import markdownify


class UnreadableFileError(ValueError):
    """The file yields no text; the message is written for the user."""


@dataclass(frozen=True)
class FileKind:
    extractor: str
    content_type: str
    label: str


PDF = FileKind("pdf", "application/pdf", "PDF")
DOCX = FileKind(
    "docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "Word document",
)
_MARKDOWN = FileKind("text", "text/markdown", "Markdown file")
_KINDS_BY_EXTENSION = {
    ".pdf": PDF,
    ".docx": DOCX,
    ".txt": FileKind("text", "text/plain", "text file"),
    ".md": _MARKDOWN,
    ".markdown": _MARKDOWN,
    ".csv": FileKind("text", "text/csv", "CSV file"),
    ".tsv": FileKind("text", "text/tab-separated-values", "TSV file"),
    ".tex": FileKind("text", "application/x-tex", "LaTeX file"),
}
_KINDS_BY_CONTENT_TYPE = {
    kind.content_type: kind for kind in _KINDS_BY_EXTENSION.values()
}
SUPPORTED_EXTENSIONS = tuple(_KINDS_BY_EXTENSION)

# Written under the ``[Page N]`` marker of a page with content but no text.
NO_TEXT_LAYER = "[This page has no text layer; it may be a scan or a figure.]"
OCR_NOTE = "[Text on this page was read by OCR and may contain errors.]"

# Bounds on work an adversarial file can demand, beyond the upload size cap.
_MAX_PDF_PAGES = 2000
_MAX_DOCX_XML_BYTES = 64 * 1024 * 1024
# A compressed PDF page or a tree of millions of tiny XML elements costs far
# more than the file's size before any text cap applies, so PDF and Word files
# are parsed in a child process under these limits.
_CHILD_CPU_SECONDS = 60
_CHILD_MEMORY_BYTES = 1024 * 1024 * 1024
_CHILD_TIMEOUT_SECONDS = 120

# Claude rejects images over 2000 px a side once a request carries more than 20.
MAX_IMAGE_EDGE_PX = 2000
# Hard ceiling for any render: an RGB pixmap this size is 48 MB in the child.
_MAX_RENDER_EDGE_PX = 4000
_MIN_RENDER_EDGE_PX = 256
_JPEG_QUALITY = 85
_IMAGE_MEDIA_TYPES = {"jpeg": "image/jpeg", "png": "image/png"}

# Text for the PDF pages it is called with (1-based); pages it omits stay marked.
PageRecovery = Callable[[Sequence[int]], Mapping[int, str]]


@dataclass(frozen=True)
class ExtractedText:
    text: str
    page_count: int | None
    truncated: bool
    # 1-based PDF pages left with ``NO_TEXT_LAYER``: no text layer, no OCR text.
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
        return _KINDS_BY_EXTENSION.get(extension)
    return kind_for_content_type(content_type.split(";")[0].strip().lower())


def kind_for_content_type(content_type: str) -> FileKind | None:
    return _KINDS_BY_CONTENT_TYPE.get(content_type)


def extract_text(
    data: bytes,
    kind: FileKind,
    *,
    max_chars: int,
    recover_pages: PageRecovery | None = None,
) -> ExtractedText:
    """Text of the file, cut at ``max_chars``. Raises ``UnreadableFileError``.

    ``recover_pages`` supplies text for PDF pages that have no text layer.
    """
    pages_without_text: tuple[int, ...] = ()
    ocr_pages: tuple[int, ...] = ()
    if kind.extractor == "text":
        text, page_count, truncated = _plain_text(data), None, False
    elif kind.extractor == "pdf":
        output = _run_child("pdf", data, label=kind.label, max_chars=max_chars)
        page_count, truncated = output["page_count"], output["truncated"]
        text, pages_without_text, ocr_pages = _assemble_pdf(
            output["pages"], recover_pages
        )
    else:
        output = _run_child(kind.extractor, data, label=kind.label, max_chars=max_chars)
        text, page_count, truncated = output["text"], None, output["truncated"]
    # Postgres text columns cannot hold NUL.
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text, truncated = text[:max_chars], True
    # An empty Word table still renders its Markdown frame.
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
) -> PageImage:
    """PDF page ``page`` (1-based) as an image. Raises ``UnreadableFileError``.

    Neither side exceeds ``max_edge_px``; the image is scaled down further
    until it fits ``max_bytes``.
    """
    if image_format not in _IMAGE_MEDIA_TYPES:
        raise ValueError(f"unsupported image format: {image_format!r}")
    if page < 1 or dpi < 1 or max_edge_px < 1 or max_bytes < 1:
        raise ValueError("page, dpi, max_edge_px and max_bytes must be positive")
    output = _run_child(
        "render",
        data,
        label=PDF.label,
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


def _assemble_pdf(
    pages: list[str | None], recover_pages: PageRecovery | None
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """Join page texts under their markers; ``None`` is a page with no text layer."""
    missing = [number for number, text in enumerate(pages, start=1) if text is None]
    recovered: dict[int, str] = {}
    if missing and recover_pages is not None:
        for number, text in recover_pages(missing).items():
            if number in missing and text and text.strip():
                recovered[number] = text.strip()
    if not any(pages) and not recovered:
        raise UnreadableFileError(
            "This PDF has no selectable text; it may be a scanned image. Upload "
            "a version with a text layer."
        )
    parts = []
    for number, text in enumerate(pages, start=1):
        if number in recovered:
            text = f"{OCR_NOTE}\n{recovered[number]}"
        elif text is None:
            text = NO_TEXT_LAYER
        parts.append(f"[Page {number}]\n{text}")
    return (
        "\n\n".join(parts),
        tuple(number for number in missing if number not in recovered),
        tuple(sorted(recovered)),
    )


def _run_child(mode: str, data: bytes, *, label: str, **options) -> dict:
    too_complex = UnreadableFileError(f"This {label} is too complex to read.")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                os.path.abspath(__file__),
                mode,
                str(_CHILD_CPU_SECONDS),
                str(_CHILD_MEMORY_BYTES),
                json.dumps(options),
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_CHILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise too_complex from exc
    if result.returncode != 0:
        raise too_complex
    output = json.loads(result.stdout)
    if "error" in output:
        raise UnreadableFileError(output["error"])
    return output


def _child_main(mode: str, cpu_seconds: int, memory_bytes: int, options: dict) -> None:
    """Child-process entry point: file on stdin, JSON result on stdout."""
    # MuPDF prints its errors to stdout; route them to stderr, off the result.
    result = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    # macOS rejects address-space limits; Linux workers enforce them.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    work = {"pdf": _pdf_pages, "docx": _docx_text, "render": _pdf_page_image}[mode]
    data = sys.stdin.buffer.read()
    try:
        output = work(data, **options)
    except UnreadableFileError as exc:
        output = {"error": str(exc)}
    with result:
        json.dump(output, result)


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
    return document


def _pdf_pages(data: bytes, max_chars: int) -> dict:
    """Each page's text; ``None`` for a page with content but no text layer."""
    with _open_pdf(data) as document:
        page_count = document.page_count
        pages: list[str | None] = []
        # No more than max_chars reaches the unlimited parent.
        remaining = max_chars
        cut = False
        try:
            for number, page in enumerate(document, start=1):
                if remaining <= 0 or number > _MAX_PDF_PAGES:
                    break
                page_text = page.get_text().strip()
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
    return {
        "pages": pages,
        "page_count": page_count,
        "truncated": cut or len(pages) < page_count,
    }


def _pdf_page_image(
    data: bytes,
    page: int,
    dpi: int,
    max_edge_px: int,
    image_format: str,
    max_bytes: int,
) -> dict:
    with _open_pdf(data) as document:
        if page > document.page_count:
            raise UnreadableFileError(f"This PDF has no page {page}.")
        try:
            pdf_page = document[page - 1]
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
                scale *= 0.7
        except Exception as exc:  # noqa: BLE001 - a damaged page stream
            raise UnreadableFileError("This PDF page could not be rendered.") from exc
    if len(image) > max_bytes:
        raise UnreadableFileError("This PDF page is too detailed to render.")
    return {
        "image": base64.b64encode(image).decode("ascii"),
        "width": pixmap.width,
        "height": pixmap.height,
    }


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


if __name__ == "__main__":
    _child_main(sys.argv[1], *map(int, sys.argv[2:4]), json.loads(sys.argv[4]))
