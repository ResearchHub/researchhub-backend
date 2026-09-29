"""Builders for the file formats chat uploads accept."""

import io
import zipfile

import fitz

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
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


def docx_bytes(body_xml: str, *, doctype: str = "") -> bytes:
    """A minimal .docx whose body is ``body_xml`` (WordprocessingML)."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>{doctype}'
        f'<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}">'
        f"<w:body>{body_xml}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"

