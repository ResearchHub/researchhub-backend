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
