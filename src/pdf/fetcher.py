import abc
from urllib import parse
from typing import List

class Fetcher(abc.ABC):
    '''Abstract Fetcher API.
    '''

    @abc.abstractclassmethod
    def hosts(cls)-> List[str]:
        '''hosts returns the list of hosts this fetcher can handle.
        '''
        pass

    @abc.abstractclassmethod
    def fetch(self, url: str)-> str:
        '''fetch_pdf extracts and returns the PDF contents.
        If no PDf content was found, None is returned.
        '''
        pass


class SciHubFetcher(Fetcher):
    @classmethod
    def hosts(cls)-> List[str]:
        return [
            "sci-hub.se",
        ]

    @classmethod
    def fetch(cls, url: str)-> str:
        pass

# A list of all available fetchers...
FETCHERS = [
    SciHubFetcher,
]

def fetch_pdf(url: str)-> str:
    '''
    fetch_pdf returns possible PDF content at the given url by extracting the web content from the given url.
    If no PDF content can be found, None is returned.
    '''
    parsed = parse.urlparse(url)
    if parsed.hostname is None:  # parsing failed.
        return None

    for fetcher in FETCHERS:
        if parsed.hostname in fetcher.hosts():
            return fetcher.fetch(url)

    return None
