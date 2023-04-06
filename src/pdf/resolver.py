import abc
import random
from typing import Tuple

import bs4  # beautifulsoup: a package to parse HTML page.

from web_scraping import *

class Resolver(abc.ABC):
    '''Resolver API.
    '''

    @abc.abstractclassmethod
    def resolve(self, doi: str)-> Tuple[str, dict]:
        '''resolve retrieves (and parses) the web contents, and returns the PDF content and associated metadata.
        '''
        pass


class SciHubResolver(Resolver):
    '''A custom resovler for sci-hub.
    '''
    HOSTS = [
        "sci-hub.se",
    ]

    @classmethod
    def resolve(self, doi: str)-> Tuple[str, dict]:
        resp = web_scrape("https://%s/%s" % (random.choice(SciHubResolver.HOSTS), doi))
        soup = bs4.BeautifulSoup(resp.text, 'html.parser')

        article_div = soup.body.find(id="article")
        if article_div is not None:
            return (
                str(article_div.children[0]),
                {
                    "doi": self._doi,
                })
        else:
            return None


class ResearchGateResolver(Resolver):
    '''A custom resolver for ResearchGate.
    '''

    @classmethod
    def resolve(self, doi: str)-> Tuple[str, dict]:
        pass
