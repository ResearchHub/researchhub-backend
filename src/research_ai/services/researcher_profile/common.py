"""Small helpers shared across the researcher_profile modules."""


def search_name(expert) -> str:
    parts = [
        getattr(expert, "first_name", ""),
        getattr(expert, "middle_name", ""),
        getattr(expert, "last_name", ""),
    ]
    return " ".join(str(p).strip() for p in parts if p and str(p).strip()).strip()


def source_urls(expert) -> list[str]:
    urls: list[str] = []
    for item in getattr(expert, "sources", None) or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        elif isinstance(item, str):
            url = item.strip()
        else:
            url = ""
        if url:
            urls.append(url)
    return urls


def candidate_institution_names(record: dict) -> list[str]:
    """Institution display names found anywhere on an OpenAlex author record."""
    names: list[str] = []
    for inst in record.get("last_known_institutions") or []:
        dn = (inst or {}).get("display_name")
        if dn:
            names.append(dn)
    lki = record.get("last_known_institution") or {}
    if lki.get("display_name"):
        names.append(lki["display_name"])
    for aff in record.get("affiliations") or []:
        inst = (aff or {}).get("institution") or {}
        if inst.get("display_name"):
            names.append(inst["display_name"])
    return names
