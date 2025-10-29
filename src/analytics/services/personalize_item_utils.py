"""
Utility functions for AWS Personalize item data export.

Functions for text cleaning, hub mapping, author extraction,
and metrics aggregation.
"""

import re
from typing import List, Optional

from analytics.constants.personalize_constants import DELIMITER, MAX_TEXT_LENGTH


def clean_text_for_csv(text: Optional[str]) -> Optional[str]:
    """
    Clean text to be CSV-safe.

    Strips HTML tags, removes/escapes problematic characters,
    and truncates to maximum length.

    Args:
        text: Raw text that may contain HTML, newlines, etc.

    Returns:
        Cleaned text safe for CSV, or None if input is None/empty
    """
    if not text:
        return None

    # Strip HTML tags using regex
    text = re.sub(r"<[^>]+>", "", text)

    # Remove or replace problematic characters for CSV
    # Replace newlines and tabs with spaces
    text = re.sub(r"[\n\r\t]+", " ", text)

    # Replace multiple spaces with single space
    text = re.sub(r"\s+", " ", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    # Truncate if too long
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    return text if text else None


def get_author_ids(unified_doc, document) -> Optional[str]:
    """
    Get comma-separated author IDs for a document.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance
        document: The concrete document (Paper or Post)

    Returns:
        Comma-separated string of author IDs, or None
    """
    author_ids = []

    try:
        # CASE 1: GRANT documents - use grant's contacts
        if unified_doc.document_type == "GRANT":
            grant = unified_doc.grants.first()
            if grant:
                for contact_user in grant.contacts.all():
                    if hasattr(contact_user, "author_profile"):
                        author_profile = contact_user.author_profile
                        if author_profile:
                            author_ids.append(str(author_profile.id))

        # CASE 2: Papers - use authorships, fallback to raw_authors
        elif hasattr(document, "authorships"):
            authorships = document.authorships.select_related("author").filter(
                author__claimed=True
            )
            if authorships.exists():
                author_ids = [str(a.author.id) for a in authorships]
            else:
                # Fallback to raw_authors JSON
                author_ids = _extract_author_ids_from_raw(document)

        # CASE 3: Posts - use authors ManyToMany
        elif hasattr(document, "authors"):
            post_authors = document.authors.all()
            if post_authors.exists():
                author_ids = [str(a.id) for a in post_authors]
            # Fallback to created_by if no authors assigned
            elif hasattr(document, "created_by") and document.created_by:
                if hasattr(document.created_by, "author_profile"):
                    author_profile = document.created_by.author_profile
                    if author_profile:
                        author_ids = [str(author_profile.id)]

        # CASE 4: Fallback for any other document type - use created_by
        elif hasattr(document, "created_by") and document.created_by:
            if hasattr(document.created_by, "author_profile"):
                author_profile = document.created_by.author_profile
                if author_profile:
                    author_ids = [str(author_profile.id)]
    except Exception:
        pass

    return DELIMITER.join(author_ids) if author_ids else None


def _extract_author_ids_from_raw(paper) -> List[str]:
    """
    Extract author IDs from paper.raw_authors JSON field.
    Matches authors by ORCID ID first, then falls back to OpenAlex ID.

    Args:
        paper: Paper instance with raw_authors JSON field

    Returns:
        List of author ID strings (only claimed authors)
    """
    from user.related_models.author_model import Author

    author_ids = []

    if not paper.raw_authors or not isinstance(paper.raw_authors, list):
        return author_ids

    for raw_author in paper.raw_authors:
        author = None

        # OPTION 1: Try matching by ORCID ID (most reliable)
        orcid = raw_author.get("orcid")
        if orcid:
            try:
                # Try matching with the full ORCID (as stored in DB)
                author = Author.objects.filter(orcid_id=orcid).first()

                # If not found, try extracting just the ID part
                if not author and "orcid.org/" in orcid:
                    orcid_id = orcid.split("orcid.org/")[-1]
                    author = Author.objects.filter(orcid_id=orcid_id).first()
            except Exception:
                pass

        # OPTION 2: Fall back to OpenAlex ID if ORCID didn't match
        if not author:
            open_alex_id = raw_author.get("open_alex_id")
            if open_alex_id:
                try:
                    author = Author.objects.filter(
                        openalex_ids__contains=[open_alex_id]
                    ).first()
                except Exception:
                    pass

        # Add author ID if found and claimed
        if author and author.claimed:
            author_ids.append(str(author.id))

    return author_ids
