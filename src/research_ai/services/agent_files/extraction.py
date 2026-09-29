"""Text extraction for files users attach to Research AI chats.

Agents read attachments as text, so every supported format reduces to one
string: PDF pages via PyMuPDF, each introduced by a ``[Page N]`` marker the
agent can cite; Word documents from their body XML; text formats by decoding.
"""

import codecs
import io
import os
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

import fitz
from lxml import etree


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

# Bounds on work an adversarial file can demand, beyond the upload size cap.
_MAX_PDF_PAGES = 2000
_MAX_DOCX_XML_BYTES = 64 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Alternate renderings of the same content; reading both would duplicate it.
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_DOCX_CONTAINERS = frozenset({f"{_W}sdt", f"{_W}sdtContent", f"{_W}customXml"})
_DOCX_RUN_TEXT = {
    f"{_W}tab": "\t",
    f"{_W}br": "\n",
    f"{_W}cr": "\n",
    f"{_W}noBreakHyphen": "-",
}


@dataclass(frozen=True)
class ExtractedText:
    text: str
    page_count: int | None
    truncated: bool


def resolve_kind(filename: str, content_type: str = "") -> FileKind | None:
    """The kind a file uploads as: by extension, else by its declared MIME type."""
    extension = os.path.splitext(filename)[1].lower()
    if extension:
        return _KINDS_BY_EXTENSION.get(extension)
    return kind_for_content_type(content_type.split(";")[0].strip().lower())


def kind_for_content_type(content_type: str) -> FileKind | None:
    return _KINDS_BY_CONTENT_TYPE.get(content_type)


def extract_text(data: bytes, kind: FileKind, *, max_chars: int) -> ExtractedText:
    """Text of the file, cut at ``max_chars``. Raises ``UnreadableFileError``."""
    extractor = {
        "pdf": _pdf_text,
        "docx": _docx_text,
        "text": _plain_text,
    }[kind.extractor]
    text, page_count, truncated = extractor(data, max_chars)
    # Postgres text columns cannot hold NUL.
    text = text.replace("\x00", "")
    if not text.strip():
        raise UnreadableFileError("No readable text was found in this file.")
    if len(text) > max_chars:
        text, truncated = text[:max_chars], True
    return ExtractedText(text=text, page_count=page_count, truncated=truncated)


def _pdf_text(data: bytes, max_chars: int) -> tuple[str, int, bool]:
    not_a_pdf = UnreadableFileError("This file could not be read as a PDF.")
    # MuPDF "repairs" arbitrary bytes into an empty document rather than fail;
    # the spec puts the header within the first 1024 bytes.
    if b"%PDF-" not in data[:1024]:
        raise not_a_pdf
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - MuPDF raises several types
        raise not_a_pdf from exc
    with document:
        if document.needs_pass:
            raise UnreadableFileError(
                "This PDF is password-protected. Remove the password and upload "
                "it again."
            )
        page_count = document.page_count
        if page_count == 0:
            raise not_a_pdf
        parts: list[str] = []
        length = 0
        has_text = False
        try:
            for number, page in enumerate(document, start=1):
                if length > max_chars or number > _MAX_PDF_PAGES:
                    break
                page_text = page.get_text().strip()
                has_text = has_text or bool(page_text)
                part = f"[Page {number}]\n{page_text}"
                parts.append(part)
                length += len(part) + 2
        except Exception as exc:  # noqa: BLE001 - a damaged page stream
            raise UnreadableFileError("This PDF could not be read.") from exc
    if not has_text:
        raise UnreadableFileError(
            "This PDF has no selectable text; it may be a scanned image. Upload "
            "a version with a text layer."
        )
    return "\n\n".join(parts), page_count, len(parts) < page_count


def _docx_text(data: bytes, max_chars: int) -> tuple[str, None, bool]:
    unreadable = UnreadableFileError(
        "This file could not be read as a Word document (.docx)."
    )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_DOCX_XML_BYTES:
                raise UnreadableFileError("This Word document is too large to read.")
            xml = archive.read(info)
    except UnreadableFileError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt archives raise many types
        raise unreadable from exc
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=True, remove_pis=True
    )
    try:
        body = etree.fromstring(xml, parser).find(f"{_W}body")
        if body is None:
            raise unreadable
        lines: list[str] = []
        length = 0
        for line in _docx_blocks(body):
            lines.append(line)
            length += len(line) + 1
            if length > max_chars:
                return "\n".join(lines), None, True
    except (etree.XMLSyntaxError, RecursionError) as exc:
        raise unreadable from exc
    return "\n".join(lines), None, False


def _docx_blocks(element) -> Iterator[str]:
    """One line per paragraph or table row, in document order."""
    for child in element:
        if child.tag == f"{_W}p":
            yield _docx_paragraph(child)
        elif child.tag == f"{_W}tbl":
            for row in child.iterfind(f"{_W}tr"):
                cells = [
                    " ".join(filter(None, _docx_blocks(cell)))
                    for cell in row.iterfind(f"{_W}tc")
                ]
                yield " | ".join(cells)
        elif child.tag in _DOCX_CONTAINERS:
            yield from _docx_blocks(child)


def _docx_paragraph(paragraph) -> str:
    parts: list[str] = []

    def walk(element) -> None:
        for node in element:
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            elif node.tag in _DOCX_RUN_TEXT:
                parts.append(_DOCX_RUN_TEXT[node.tag])
            elif node.tag != _MC_FALLBACK:
                walk(node)

    walk(paragraph)
    return "".join(parts)


def _plain_text(data: bytes, max_chars: int) -> tuple[str, None, bool]:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = data.decode("utf-16", errors="replace")
    elif b"\x00" in data:
        raise UnreadableFileError("This file does not contain plain text.")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, None, len(text) > max_chars
