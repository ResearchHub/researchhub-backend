from django.core.paginator import Paginator
from urllib.parse import urlparse, urlunparse
from django.http import QueryDict

def BasicPaginator(data, page_num, url, page_size=20):
    paginator = Paginator(data, page_size)
    page = paginator.page(page_num)
    nextPageNum = int(page_num) + 1
    
    (scheme, netloc, path, params, query, fragment) = urlparse(url)
    query_dict = QueryDict(query).copy()
    query_dict["page"] = nextPageNum
    query = query_dict.urlencode()
    nextPage = urlunparse((scheme, netloc, path, params, query, fragment))
    
    if not page.has_next():
        nextPage = None

    return paginator.count, nextPage, page