from copy import deepcopy

from note.models import parse_note_json

REGISTERED_REPORT_PREFILL_ATTR = "registered_report_prefill"


def add_registered_report_prefill_metadata(
    document_json: dict[str, object], metadata: dict[str, object]
) -> dict[str, object]:
    """Add registered report metadata to notebook JSON without changing content."""
    document = deepcopy(document_json)
    attrs = document.get("attrs")
    if not isinstance(attrs, dict):
        attrs = {}
    attrs[REGISTERED_REPORT_PREFILL_ATTR] = metadata
    document["attrs"] = attrs
    return document


def get_registered_report_prefill_metadata(value: object) -> dict[str, object]:
    """Return registered report metadata from notebook JSON."""
    document = parse_note_json(value)
    if document is None:
        return {}
    attrs = document.get("attrs")
    if not isinstance(attrs, dict):
        return {}
    metadata = attrs.get(REGISTERED_REPORT_PREFILL_ATTR)
    if not isinstance(metadata, dict):
        return {}
    return metadata
