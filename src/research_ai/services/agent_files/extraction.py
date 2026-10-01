"""Text extraction for files users attach to Research AI chats.

Agents read attachments as text, so every supported format reduces to one
string: PDF pages via PyMuPDF, each introduced by a ``[Page N]`` marker the
agent can cite; Word documents as Markdown via mammoth; text formats by decoding.
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

# Bounds on work an adversarial file can demand, beyond the upload size cap.
_MAX_PDF_PAGES = 2000
_MAX_DOCX_XML_BYTES = 64 * 1024 * 1024
# A compressed PDF page or a tree of millions of tiny XML elements costs far
# more than the file's size before any text cap applies, so PDF and Word files
# are parsed in a child process under these limits.
_CHILD_CPU_SECONDS = 60
_CHILD_MEMORY_BYTES = 1024 * 1024 * 1024
_CHILD_TIMEOUT_SECONDS = 120


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
        text, page_count, truncated = _plain_text(data), None, False
    else:
        text, page_count, truncated = _extract_in_child(kind, data, max_chars)
    # Postgres text columns cannot hold NUL.
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text, truncated = text[:max_chars], True
    # An empty Word table still renders its Markdown frame.
    if not any(map(str.isalnum, text)):
        raise UnreadableFileError("No readable text was found in this file.")
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
    return text, None, len(text) > max_chars


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
    _child_main(sys.argv[1], *map(int, sys.argv[2:5]))
