"""Text extraction for files users attach to Research AI chats.

Agents read attachments as text, so every supported format reduces to one
string: PDF pages via PyMuPDF, each introduced by a ``[Page N]`` marker the
agent can cite; Word documents from their body XML; text formats by decoding.
"""

import codecs
import contextlib
import io
import json
import os
import resource
import subprocess
import sys
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
# A compressed PDF page or a tree of millions of tiny XML elements costs far
# more than the file's size before any text cap applies, so PDF and Word files
# are parsed in a child process under these limits.
_CHILD_CPU_SECONDS = 60
_CHILD_MEMORY_BYTES = 1024 * 1024 * 1024
_CHILD_TIMEOUT_SECONDS = 120

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W_STRICT = "{http://purl.oclc.org/ooxml/wordprocessingml/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_DOCX_CONTAINERS = frozenset({f"{_W}sdt", f"{_W}sdtContent", f"{_W}customXml"})
# No visible text: formatting properties (tab stops there are w:tab elements
# too) and tracked changes that are no longer part of the document.
_DOCX_SKIPPED = frozenset({f"{_W}pPr", f"{_W}rPr", f"{_W}del", f"{_W}moveFrom"})
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
    if kind.extractor == "text":
        text, page_count, truncated = _plain_text(data, max_chars)
    else:
        text, page_count, truncated = _extract_in_child(kind, data, max_chars)
    # Postgres text columns cannot hold NUL.
    text = text.replace("\x00", "")
    if not text.strip():
        raise UnreadableFileError("No readable text was found in this file.")
    if len(text) > max_chars:
        text, truncated = text[:max_chars], True
    return ExtractedText(text=text, page_count=page_count, truncated=truncated)


def _extract_in_child(
    kind: FileKind, data: bytes, max_chars: int
) -> tuple[str, int | None, bool]:
    too_complex = UnreadableFileError(f"This {kind.label} is too complex to read.")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                os.path.abspath(__file__),
                kind.extractor,
                str(max_chars),
                str(_CHILD_CPU_SECONDS),
                str(_CHILD_MEMORY_BYTES),
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
    return output["text"], output["page_count"], output["truncated"]


def _child_main(
    extractor: str, max_chars: int, cpu_seconds: int, memory_bytes: int
) -> None:
    """Child-process entry point: file on stdin, JSON result on stdout."""
    # MuPDF prints its errors to stdout; route them to stderr, off the result.
    result = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    # macOS rejects address-space limits; Linux workers enforce them.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    parse = {"pdf": _pdf_text, "docx": _docx_text}[extractor]
    data = sys.stdin.buffer.read()
    try:
        text, page_count, truncated = parse(data, max_chars)
        # Cut here so no more than max_chars reaches the unlimited parent.
        output = {
            "text": text[:max_chars],
            "page_count": page_count,
            "truncated": truncated or len(text) > max_chars,
        }
    except UnreadableFileError as exc:
        output = {"error": str(exc)}
    with result:
        json.dump(output, result)


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
        root = etree.fromstring(xml, parser)
        if root.tag.startswith(_W_STRICT):
            _to_transitional(root)
        body = root.find(f"{_W}body")
        if body is None:
            raise unreadable
        _resolve_alternate_content(body)
        lines: list[str] = []
        length = -1  # the first line has no separator before it
        for line in _docx_blocks(body):
            lines.append(line)
            length += len(line) + 1
            if length > max_chars:
                break
    except (etree.XMLSyntaxError, RecursionError) as exc:
        raise unreadable from exc
    text = "\n".join(lines)
    return text, None, len(text) > max_chars


def _to_transitional(root) -> None:
    """Rename Strict OOXML elements into the Transitional namespace."""
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.startswith(_W_STRICT):
            element.tag = _W + element.tag[len(_W_STRICT) :]


def _resolve_alternate_content(element) -> None:
    """Replace each mc:AlternateContent with its first rendering that has text."""
    for alternate in list(element.iter(f"{_MC}AlternateContent")):
        # Choices in order, then the fallback; a choice may be only a drawing.
        renderings = (
            *alternate.iterfind(f"{_MC}Choice"),
            *alternate.iterfind(f"{_MC}Fallback"),
        )
        chosen = next(
            (r for r in renderings if any(t.text for t in r.iter(f"{_W}t"))), None
        )
        parent = alternate.getparent()
        position = parent.index(alternate)
        parent[position : position + 1] = [] if chosen is None else list(chosen)


def _docx_children(element, tag: str) -> Iterator:
    """Children with ``tag``, looking through content-control wrappers."""
    for child in element:
        if child.tag == tag:
            yield child
        elif child.tag in _DOCX_CONTAINERS:
            yield from _docx_children(child, tag)


def _docx_blocks(element) -> Iterator[str]:
    """One line per paragraph or table row, in document order."""
    for child in element:
        if child.tag == f"{_W}p":
            yield _docx_paragraph(child)
        elif child.tag == f"{_W}tbl":
            for row in _docx_children(child, f"{_W}tr"):
                cells = [
                    " ".join(filter(None, _docx_blocks(cell)))
                    for cell in _docx_children(row, f"{_W}tc")
                ]
                if any(cell.strip() for cell in cells):
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
            elif node.tag not in _DOCX_SKIPPED:
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


if __name__ == "__main__":
    _child_main(sys.argv[1], *map(int, sys.argv[2:5]))
