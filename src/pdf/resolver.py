import abc
import random
import re
import requests
from urllib import parse

import bs4  # beautifulsoup4: a package to parse HTML page.

from web_scraping import *

class NotImplementedError(Exception):
    pass

class Resolver(abc.ABC):
    '''Resolver API.
    '''
    doi_re = re.compile(r"10.\d{4,9}/[-._;()/:a-z0-9A-Z]+")

    @abc.abstractclassmethod
    def hosts(cls)-> list[str]:
        '''hosts returns the list of host for this particular Resolver subclass.'''
        pass

    @abc.abstractclassmethod
    def from_doi(cls, doi: str)-> str:
        '''from_doi returns the container url for the given doi.
        '''
        pass

    @classmethod
    def parse(cls, resp: requests.models.Response, meta: dict)-> dict:
        '''parse parses the given web page and returns the retrieved PDF metadata.

        The default behavior is to get the text of the web page and return anything that looks like a doi.

        NOTE(kevinyang):
        Any parsing logic is inherely brittle as it's subject to the HTML structure, which is totally outside our control.
        This logic needs to continuously react to any breaking changes from the remote site.
        '''
        if meta.get('doi', None) is None:
            soup = bs4.BeautifulSoup(resp.text, 'html.parser')
            matched = Resolver.doi_re.search(soup.get_text())
            if matched:
                meta['doi'] = matched.group()

        return meta

    @classmethod
    def fetch(cls, url: str, proxies: dict = None, verify: bool = True)-> dict:
        '''fetch retrieves (and parses) the web contents for the given url, and returns the associated metadata.
        '''
        resp = web_scrape(url, proxies=proxies, verify=verify)
        return cls.parse(resp, {})

    @classmethod
    def fetch_by_doi(cls, doi: str, proxies: dict = None, verify: bool = True)-> dict:
        '''fetch_by_doi retrieves (and parses) the web contents for the given doi, and returns the associated metadata.
        '''
        resp = web_scrape(cls.from_doi(doi), proxies=proxies, verify=verify)
        return cls.parse(resp, {'doi': doi})


class SciHubResolver(Resolver):
    '''A custom resovler for sci-hub.
    '''
    pdf_url_re = re.compile(r"location.href='(//.+)\?download=true'")

    @classmethod
    def hosts(cls)-> list[str]:
        return [
            "sci-hub.se",
        ]

    @classmethod
    def from_doi(cls, doi: str)-> str:
        host = random.choice(cls.hosts())
        return f"https://{host}/{doi}"

    @classmethod
    def parse(cls, resp: requests.models.Response, meta: dict)-> dict:
        soup = bs4.BeautifulSoup(resp.text, 'html.parser')

        try:
            # The download url is located at: body-> #minu-> #buttons-> button['onclock']
            # One example for the 'onclick' attribute:
            # location.href='//moscow.sci-hub.se/4746/234245eed78d3448735c796a77f10f85/laiho2015.pdf?download=true'
            buttons = soup.body.find_next(id="minu").find_next(id="buttons")
            button = buttons.find("button")
            matched = SciHubResolver.pdf_url_re.match(button.get('onclick'))
            if matched is not None:
                meta['pdf_url'] = f"https:{matched.group(1)}"

            if meta['doi'] is None:
                # Try to recover doi from the page as well, if it's still unknown.
                doi = buttons.find_next(id="citation").find_next(id="doi")
                meta['doi'] = doi.text
        except AttributeError:
            pass

        return meta


class ResearchGateResolver(Resolver):
    '''A custom resolver for researchgate.
    '''

    @classmethod
    def hosts(cls)-> list[str]:
        return [
            "researchgate.net",
            "www.researchgate.net",
            ]

    @classmethod
    def from_doi(cls, doi: str)-> str:
        '''Not supported for researchgate.'''
        raise NotImplementedError

    @classmethod
    def parse(cls, resp: requests.models.Response, meta: dict)-> dict:
        soup = bs4.BeautifulSoup(resp.text, 'html.parser')

        try:
            header = soup.body.find('div', class_='content-page-header')
            if meta.get('doi', None) is None:
                meta_div = header.find('div', class_="research-detail-meta")
                uls = meta_div.find_all("ul")
                doi_anchor = uls[1].find('a')
                meta['doi'] = doi_anchor.string

            download_span = header.find('span', string='Download')
            href = download_span.parent.get('href')
            parsed = parse.urlparse(href)
            meta['pdf_url'] = parse.urlunparse([parsed.scheme, parsed.netloc, parsed.path, '', '', ''])
        except AttributeError:
            pass

        return meta


# Registered resolvers.
RESOLVERS = [
    SciHubResolver,
    ResearchGateResolver,
]

def fetch(url: str, proxies: dict = None, verify: bool = True)-> dict:
    '''fetch returns the associated PDF metadata found in the container page (as indicated by the url).

    To use with zenrows service:
        fetch(url, ZENROWS_PROXIES, False)
    '''
    parsed = parse.urlparse(url)
    for resolver in RESOLVERS:
        if parsed.hostname in resolver.hosts():
            return resolver.fetch(url, proxies=proxies, verify=verify)

    # Default resolver, as last resort.
    return Resolver.fetch(url, proxies=proxies, verify=verify)


# TODO(kevin): Not completely working yet.
def fetch_pdf(pdf_url: str, proxies: dict = None, verify: bool = True)-> bytes:
    '''fetch_pdf returns the PDF contents, with the given downloading url.

    Note this download url is NOT the container url.
    Instead, we extract the download url from the scraped webpage, and issue another call to retrieve the PDF.

    To use with zenrows service:
        fetch_pdf(pdf_url, ZENROWS_PROXIES, False)
    '''
    resp = web_scrape(pdf_url, proxies=proxies, verify=verify)
    # Return the binary content.
    return resp.content