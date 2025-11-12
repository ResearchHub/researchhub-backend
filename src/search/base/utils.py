"""
Utilities for Elasticsearch integration.
Replaces utilities from django_elasticsearch_dsl_drf.
"""

import unicodedata

# Constants
MATCHING_OPTION_MUST = "must"
MATCHING_OPTION_SHOULD = "should"
MATCHING_OPTION_MUST_NOT = "must_not"
MATCHING_OPTION_FILTER = "filter"


class DictObject:
    """
    Simple object that allows dict access via attributes.
    """

    def __init__(self, d):
        self.__dict__.update(d)

    def __getattr__(self, name):
        return self.__dict__.get(name)

    def __setattr__(self, name, value):
        self.__dict__[name] = value

    def to_dict(self):
        return self.__dict__.copy()


def obj_to_dict(obj):
    """
    Convert an object back to a dictionary.

    Args:
        obj: Object to convert (DictObject or regular object)

    Returns:
        dict: Dictionary representation
    """
    if isinstance(obj, DictObject):
        result = {}
        for key, value in obj.__dict__.items():
            if isinstance(value, DictObject):
                result[key] = obj_to_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    obj_to_dict(item) if isinstance(item, DictObject) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
    elif hasattr(obj, "__dict__"):
        return obj.__dict__.copy()
    else:
        return obj


def normalize_text(text: str) -> str:
    """Normalize text for search by removing accents/diacritics and lowercasing.

    This uses NFD decomposition and ASCII folding to strip diacritics
    (e.g., "José" -> "jose").
    """
    if not text:
        return ""
    return (
        unicodedata.normalize("NFD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def seconds_to_milliseconds(seconds: float, decimals: int = 2) -> float:
    """Convert seconds to milliseconds with specified decimal precision."""
    return round(seconds * 1000, decimals)
