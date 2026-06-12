"""Shared factories for the researcher_profile test modules."""

from research_ai.models import Expert


def make_expert(**kwargs):
    """Unsaved Expert (no DB) for the pure-logic paths."""
    defaults = {
        "first_name": "Jane",
        "middle_name": "",
        "last_name": "Doe",
        "affiliation": "",
        "expertise": "",
        "sources": [],
    }
    defaults.update(kwargs)
    return Expert(**defaults)
