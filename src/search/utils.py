from django.utils import timezone


def get_crossref_doi(item):
    return item['DOI']


def get_crossref_issued_date(item):
    parts = item['issued']['date-parts'][0]
    day = 1
    month = 1
    if len(parts) > 2:
        day = parts[2]
    if len(parts) > 1:
        month = parts[1]
    if len(parts) > 0:
        year = parts[0]
        return timezone.datetime(year, month, day)


def get_unique_crossref_items(items):
    results = {}
    for item in items:
        if results.get(item['title'][0]) is None:
            results[item['title'][0]] = item
    return results.values()
