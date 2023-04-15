import abc
import random
import re
import requests
from urllib import parse

import bs4  # beautifulsoup4: a package to parse HTML page.

from web_scraping import *

class NotImplementedError(Exception):
    pass

class WebScrapingError(Exception):
    pass

class Resolver(abc.ABC):
    '''Resolver API.
    '''

    # Regular expression to extract doi.
    DOI_RE = re.compile(r"10.\d{4,9}/[-._;()/:a-z0-9A-Z]+")

    @abc.abstractclassmethod
    def hosts(cls)-> list[str]:
        '''hosts returns the list of host variations for this particular Resolver subclass.'''
        pass

    @abc.abstractclassmethod
    def from_doi(cls, doi: str)-> str:
        '''from_doi returns the container url for the given doi.
        '''
        pass

    @classmethod
    def parse(cls, resp: requests.models.Response, meta: dict)-> dict:
        '''parse parses the given web page and returns the retrieved PDF metadata.

        The default behavior is to get the text of the page and return the first match that looks like a doi.

        NOTE(kevinyang):
        Any parsing logic is inherely brittle as it's subject to the HTML structure, which is totally outside our control.
        This logic (especially in the custom Resolver) needs to continuously react to breaking changes from the remote site.
        '''

        if 'doi' not in meta:
            soup = bs4.BeautifulSoup(resp.text, 'html.parser')
            for string in soup.stripped_strings:
                matched = Resolver.DOI_RE.search(string)
                if matched:
                    meta['doi'] = matched.group()
                    break

        return meta

    @classmethod
    def fetch(cls, url: str, proxies: dict = None, verify: bool = True)-> dict:
        '''fetch retrieves (and parses) the web contents for the given url, and returns the associated metadata.
        raise WebScrapingError if the scraping failed for any reason.
        '''

        resp = web_scrape(url, proxies=proxies, verify=verify)
        if not resp.ok:
            raise WebScrapingError

        #with open("resp.html", "w") as f:
        #    f.write(resp.text)

        return cls.parse(resp, {})

    @classmethod
    def fetch_by_doi(cls, doi: str, proxies: dict = None, verify: bool = True)-> dict:
        '''fetch_by_doi retrieves (and parses) the web contents for the given doi, and returns the associated metadata.
        raise WebScrapingError if the scraping failed for any reason.
        '''

        resp = web_scrape(cls.from_doi(doi), proxies=proxies, verify=verify)
        if not resp.ok:
            raise WebScrapingError

        return cls.parse(resp, {'doi': doi})


class SciHubResolver(Resolver):
    '''A custom resovler for sci-hub.
    '''

    # download url pattern for SciHub pages.
    SITE = re.compile(r"//(.+)/")

    PDF_URL_SAME_SITE = re.compile(r"location.href='(/.*)\?download=true'")
    PDF_URL_MIRROR_SITE = re.compile(r"location.href='//([^/]+)(/.+)\?download=true'")

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

        if 'doi' not in meta:
            # Try to recover doi from the page as well, if it's still unknown.
            doi = soup.body.find(id="doi")
            if doi:
                meta['doi'] = doi.text.strip()

        buttons = soup.body.find(id="buttons")
        if not buttons:
            return meta

        # The download url is located at: body-> #minu-> #buttons-> button['onclock']
        #
        # Several case for the 'onclick' attribute:
        # 1. same host:
        #   location.href='/downloads/2020-04-10/08/emmert-streib2020.pdf?download=true'
        # 2. another mirror site:
        #   location.href='//moscow.sci-hub.se/4746/234245eed78d3448735c796a77f10f85/laiho2015.pdf?download=true'
        #
        button = buttons.find("button")
        if not button:
            return meta

        hint = button.get('onclick')
        matched = SciHubResolver.PDF_URL_MIRROR_SITE.match(hint)
        if matched:
            meta['pdf_url'] = parse.urlunparse(['https', matched.group(1), matched.group(2), '', '', ''])
            return meta

        matched = SciHubResolver.PDF_URL_SAME_SITE.match(hint)
        if matched:
            site = ''
            head_anchor = soup.body.find('a', id="header")  # body-> #minu-> a#header
            if head_anchor:
                site_match = SciHubResolver.SITE.match(head_anchor.get('href'))
                if site_match:
                    site = site_match.group(1)

            meta['pdf_url'] = parse.urlunparse(['https', site, matched.group(1), '', '', ''])
            return meta

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

        meta_doi = soup.head.find('meta', property='citation_doi')
        if meta_doi:
            meta['doi'] = meta_doi['content']

        # TODO: add 'citation_authors' etc.
        meta_title = soup.head.find('meta', property='citation_title')
        if meta_title:
            meta['title'] = meta_title['content']

        try:
            # Locate the Download button, and follow href.
            download_span = soup.body.find('span', string='Download file PDF')
            href = download_span.parent.get('href')
            meta['pdf_url'] = f"https://researchgate.net/{href}"
        except AttributeError:
            pass  # Ignore if the required web elements are missing.

        return meta


# Registered resolvers.
RESOLVERS = [
    SciHubResolver,
    ResearchGateResolver,
]

def fetch(url: str, proxies: dict = None, verify: bool = True)-> dict:
    '''fetch returns the associated PDF metadata found in the container page (as indicated by the url).
    raise WebScrapingError if the scraping failed for any reason.

    To use with zenrows service:
        fetch(url, ZENROWS_PROXIES, False)
    '''
    parsed = parse.urlparse(url)
    for resolver in RESOLVERS:
        if parsed.hostname in resolver.hosts():
            return resolver.fetch(url, proxies=proxies, verify=verify)

    # Default resolver, as last resort.
    return Resolver.fetch(url, proxies=proxies, verify=verify)


def fetch_pdf(pdf_url: str, proxies: dict = None, verify: bool = True)-> bytes:
    '''fetch_pdf returns the PDF contents, with the given downloading url.
    raise WebScrapingError if the scraping failed for any reason.

    Note this download url is NOT the container url.
    Instead, we extract the download url from the scraped webpage, and issue another call to retrieve the PDF.

    To use with zenrows service:
        fetch_pdf(pdf_url, ZENROWS_PROXIES, False)
    '''
    resp = web_scrape(pdf_url, proxies=proxies, verify=verify)
    if not resp.ok:
        raise WebScrapingError

    return resp.content  # Return the binary content.