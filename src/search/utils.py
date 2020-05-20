import math
import utils.sentry as sentry

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
    for term in terms:
        n = Paper.objects.filter(title__contains=term).count()
        s = score(n, N, dl, avgdl)
        print(f'score: {s}, n: {n}')
        total_score += s

    return total_score


def get_avgdl(es, qs):
    cache_key = 'paper_avgdl'
    avgdl = cache.get(cache_key)
    if avgdl is None:
        try:
            explanation = es.query(
                explain=True
            ).extra(
                explain=True
            ).execute().to_dict()
            print(explanation)

            hits = explanation['hits']['hits'][0]
            _explanation = hits['_explanation']
            description = _explanation['description']

            if 'sum of' in description:
                details = _explanation['details'][0]['details'][0]['details']
            else:
                details = _explanation['details']

            term_freq = details[-1]
            tf_details = term_freq['details']
            avgdl = tf_details[-1]['value']
            cache.set(cache_key, avgdl, timeout=60*60*24)
        except Exception as e:
            print(e)
            sentry.log_info('Missing Elasticsearch explanation', error=e)
            qs_count = qs.count()
            total_len = sum([len(paper.title.split()) for paper in qs])
            avgdl = max(1, (total_len / qs_count) - 1)

    return avgdl
