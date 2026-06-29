"""Shared PDF-to-text helpers for research_ai services.

Both the expert finder and the proposal draft agent need the same two
operations: get a paper's PDF bytes (preferring the S3 ``file``, falling back to
``pdf_url``/``url``) and extract readable text from those bytes with PyMuPDF.
They live here so the two call sites share one implementation.
"""

import logging

import fitz

from paper.tasks.tasks import create_download_url
from paper.utils import download_pdf_from_url

logger = logging.getLogger(__name__)

# Hard ceiling on extracted text so a huge PDF cannot blow up a prompt.
_MAX_TEXT_CHARS = 200000


def get_paper_pdf_bytes(paper) -> bytes | None:
    """Get PDF content for a paper. Prefer ``paper.file`` (S3); fall back to URL."""
    if getattr(paper, "file", None) and getattr(paper.file, "url", None):
        try:
            pdf_file = download_pdf_from_url(paper.file.url)
            return pdf_file.read()
        except Exception as e:
            logger.warning(
                "Failed to get PDF from paper.file for paper %s: %s. Trying pdf_url.",
                getattr(paper, "id", "?"),
                e,
            )

    pdf_url = getattr(paper, "pdf_url", None) or getattr(paper, "url", None)
    if not pdf_url:
        return None
    try:
        url = create_download_url(pdf_url, getattr(paper, "external_source", "") or "")
        pdf_file = download_pdf_from_url(url)
        return pdf_file.read()
    except Exception as e:
        logger.warning(
            "Failed to download PDF from pdf_url for paper %s: %s",
            getattr(paper, "id", "?"),
            e,
            exc_info=True,
        )
        return None


def extract_text_from_pdf_bytes(
    pdf_bytes: bytes, *, max_chars: int = _MAX_TEXT_CHARS
) -> str:
    """Extract text from PDF bytes using PyMuPDF, truncated to ``max_chars``."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc]
        doc.close()
        text = "\n".join(parts)
        return text[:max_chars] if len(text) > max_chars else text
    except Exception as e:
        logger.warning("Failed to extract text from PDF: %s", e)
        raise ValueError(f"PDF text extraction failed: {e}") from e
