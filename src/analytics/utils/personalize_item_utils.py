"""
Utility functions for AWS Personalize item data export.
"""

import re
from typing import Optional

from analytics.constants.personalize_constants import MAX_TEXT_LENGTH


def prepare_text_for_personalize(text: Optional[str]) -> Optional[str]:
    """
    Prepare text for CSV export.
    """
    if not text:
        return None

    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip()

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    return text if text else None
