import math
import utils.sentry as sentry

from django.db.models import Q, Count
from django.core.cache import cache
from django.utils import timezone

from paper.models import Paper


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


def tf_calc(dl, avgdl):
    freq = 1
    k1 = 1.2
    b = 0.75
    return freq / (freq + k1 * (1 - b + b * dl / avgdl))


def idf_calc(n, N):
    return math.log(1 + (N - n + 0.5) / (n + 0.5))


def score(n, N, dl, avgdl):
    boost = 2.2
    idf = idf_calc(n, N)
    tf = tf_calc(dl, avgdl)
    val = boost * idf * tf
    return val


def practical_score(terms, N, dl, avgdl):
    total_score = 0
    aggregate_dict = {}
    for term in terms:
        aggregate_dict[term] = Count('pk', filter=Q(title__contains=term))

    counts = Paper.objects.aggregate(**aggregate_dict)
    for n in counts.values():
        s = score(n, N, dl, avgdl)
        total_score += s

    return total_score


def get_avgdl_from_hit(hit):
    details = hit['details'][::-1]
    for detail in details:
        description = detail['description']

        if 'average length of field' in description:
            return detail['value']

        res = get_avgdl_from_hit(detail)
        if type(res) is float:
            return res
    return None


def get_avgdl_from_qs(qs):
    qs_count = qs.count()
    total_len = sum(
        [len(paper.title.split()) for paper in qs.iterator()]
    )
    avgdl = max(1, (total_len / qs_count) - 1)
    return avgdl


def get_avgdl(es, qs):
    cache_key = 'paper_avgdl'
    avgdl = cache.get(cache_key)
    if avgdl is None:
        try:
            explanation = es.extra(
                explain=True
            ).execute().to_dict()
            explanation = explanation['hits']['hits']
            first_hit = explanation[0]['_explanation']

            avgdl = get_avgdl_from_hit(first_hit)
            if not avgdl:
                avgdl = get_avgdl_from_qs(qs)
                sentry.log_info('Could not find avgdl from explanation')
            else:
                cache.set(cache_key, avgdl, timeout=60*60*24)
        except Exception as e:
            sentry.log_info('Missing Elasticsearch explanation', error=e)
            avgdl = get_avgdl_from_qs(qs)

    return avgdl
