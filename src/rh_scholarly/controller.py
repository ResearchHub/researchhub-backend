from scholarly import ProxyGenerator, scholarly


def setup_free_proxy():
    pg = ProxyGenerator()
    pg.FreeProxies()
    scholarly.use_proxy(pg)


def search_for_authors(name, start_index=0):
    setup_free_proxy()
    search_query = scholarly.search_author(name)
    results = []
    for i in range(start_index, 10):
        res = next(search_query, None)
        if res is None:
            break
        results.append(res)
    return results


def author_profile_lookup(scholarly_author_id):
    setup_free_proxy()
    author = scholarly.search_author_id(scholarly_author_id)
    results = scholarly.fill(author)
    return results
