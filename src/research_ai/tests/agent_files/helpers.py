"""Builders for the file formats chat uploads accept."""

import io
import zipfile

import fitz

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_STRICT_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


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


def docx_bytes(
    body_xml: str,
    *,
    doctype: str = "",
    namespace: str = W_NS,
    parts: dict[str, str | bytes] | None = None,
) -> bytes:
    """A minimal .docx whose body is ``body_xml``; ``parts`` adds archive members."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>{doctype}'
        f'<w:document xmlns:w="{namespace}" xmlns:mc="{MC_NS}">'
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
