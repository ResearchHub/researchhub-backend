"""Small helpers shared across the researcher_profile modules."""


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
