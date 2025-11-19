"""
Utility functions for AWS Personalize item data export.
"""

import re
from typing import Optional

from personalize.config.constants import MAX_TEXT_LENGTH


def prepare_text_for_personalize(text: Optional[str]) -> Optional[str]:
    """
    Prepare text for CSV export.
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
