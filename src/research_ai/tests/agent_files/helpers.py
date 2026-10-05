"""Builders for chat file rows and the formats uploads accept."""

import io
import uuid
import zipfile

import fitz

from research_ai.models import AgentFile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SCAN = object()


def pdf_bytes(*pages: str, **save_options) -> bytes:
    """A PDF with one page per argument; an empty string is a blank page."""
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes(**save_options)
    document.close()
    return data


def stamped_scan(stamp: str) -> tuple:
    """A ``pdf_with_scans`` page: a scan with ``stamp`` as its only text."""
    return SCAN, stamp


def pdf_with_scans(*pages) -> bytes:
    """A PDF whose ``SCAN`` pages hold only an image; other pages hold text."""
    document = fitz.open()
    for content in pages:
        page = document.new_page()
        content, stamp = content if isinstance(content, tuple) else (content, "")
        if content is SCAN:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
            pixmap.clear_with(180)
            page.insert_image(page.rect, pixmap=pixmap)
            content = stamp
        if content:
            page.insert_text((72, 72), content)
    data = document.tobytes()
    document.close()
    return data


def docx_bytes(
    body_xml: str,
    *,
    doctype: str = "",
    parts: dict[str, str | bytes] | None = None,
) -> bytes:
    """A minimal .docx whose body is ``body_xml``; ``parts`` adds archive members."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>{doctype}'
        f'<w:document xmlns:w="{W_NS}">'
        f"<w:body>{body_xml}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        for name, content in (parts or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def make_file(
    user,
    *,
    message=None,
    status=AgentFile.Status.READY,
    filename="grant.pdf",
    content_type="application/pdf",
    text="[Page 1]\nSpecific aims",
    **fields,
) -> AgentFile:
    """A file row as the upload lifecycle leaves it; sent when ``message``."""
    return AgentFile.objects.create(
        user=user,
        conversation=message.conversation if message is not None else None,
        message=message,
        filename=filename,
        content_type=content_type,
        size_bytes=fields.pop("size_bytes", 100),
        storage_key=f"uploads/research_ai/users/{user.id}/{uuid.uuid4()}/{filename}",
        status=status,
        text=text,
        **fields,
    )
