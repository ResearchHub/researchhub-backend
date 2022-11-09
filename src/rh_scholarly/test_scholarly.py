import requests
from scholarly._scholarly import _Scholarly

_AUTHSEARCH = "/citations?hl=en&view_op=search_authors&mauthors={0}&{1}"


class RHScholarly(_Scholarly):
    def __init__(self):
        super().__init__()

    def search_author(
        self,
        name: str,
    ):
        """Search by author name and return a generator of Author objects
        :Example::
            .. testcode::
                search_query = scholarly.search_author('Marty Banks, Berkeley')
                scholarly.pprint(next(search_query))
        :Output::
        .. testoutput::
            {'affiliation': 'Professor of Vision Science, UC Berkeley',
             'citedby': 21074,
             'email_domain': '@berkeley.edu',
             'filled': False,
             'interests': ['vision science', 'psychology', 'human factors', 'neuroscience'],
             'name': 'Martin Banks',
             'scholar_id': 'Smr99uEAAAAJ',
             'source': 'SEARCH_AUTHOR_SNIPPETS',
             'url_picture': 'https://scholar.google.com/citations?view_op=medium_photo&user=Smr99uEAAAAJ'}
        """
        url = _AUTHSEARCH.format(requests.utils.quote(name), f"&astart={astart}")
        return self.__nav.search_authors(url)
