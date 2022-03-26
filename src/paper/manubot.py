import logging
from functools import cached_property
from typing import Any, Dict

from manubot.cite.citekey import CiteKey
from manubot.cite.csl_item import CSL_Item
from manubot.cite.handlers import Handler
from manubot.cite.url import (
    Handler_URL,
    get_url_csl_item_manual,
    get_url_csl_item_zotero,
)

CSLItem = Dict[str, Any]

url_retrievers = [
    get_url_csl_item_zotero,
    get_url_csl_item_manual,
]


def get_url_csl_item(self, url: str) -> CSLItem:
    """
    Get csl_item for a URL trying a sequence of strategies.
    This function uses a list of CSL JSON Item metadata retrievers, specified
    by the module-level variable `url_retrievers`. The methods are attempted
    in order, with this function returning the metadata from the first
    non-failing method.
    """
    for retriever in url_retrievers:
        try:
            return retriever(url)
        except Exception as error:
            logging.warning(
                f"Error in {retriever.__name__} for {url} "
                f"due to a {error.__class__.__name__}:\n{error}"
            )
            logging.info(error, exc_info=True)
    raise Exception(f"all get_url_csl_item methods failed for {url}")


class RHHandler_URL(Handler):

    standard_prefix = "url"

    prefixes = [
        "url",
        "http",
        "https",
    ]

    def standardize_prefix_accession(self, accession):
        if self.prefix_lower != "url":
            accession = f"{self.prefix_lower}:{accession}"
        return self.standard_prefix, accession

    def get_csl_item(self, citekey):
        return get_url_csl_item(citekey.standard_accession)


class RHCiteKey(CiteKey):
    """
    Source: https://github.com/manubot/manubot/blob/main/manubot/cite/citekey.py#L17
    Modified so that get_url_csl_item won't use greycite (extremely slow)
    """

    @cached_property
    def csl_item(self):
        handler = self.handler
        if isinstance(handler, Handler_URL):
            handler = RHHandler_URL()
        csl_item = handler.get_csl_item(self)
        if not isinstance(csl_item, CSL_Item):
            csl_item = CSL_Item(csl_item)
        csl_item.set_id(self.standard_id)
        return csl_item


# TESTING ------------------------------------------------------------------------------------------------------------------------------

import time
from collections import Counter, OrderedDict
from urllib.parse import urlparse

import regex as re
import requests
from bs4 import BeautifulSoup as soup
from requests import Session


def start():
    urls = (
        Paper.objects.filter(doi__isnull=False, url__isnull=False)
        .exclude(url="")
        .values_list("url", flat=True)[:100]
    )
    results = {}
    domains = set()
    try:
        for i, url in enumerate(urls.iterator()):
            print(i)
            o = urlparse(url)
            hostname = o.hostname

            if hostname not in domains:
                domains.add(hostname)
                print(f"{i}: {url}")
            res = get_doi(url)
            results[url] = res
            time.sleep(1)
        return results
    except Exception as e:
        print(e)
        return results


def regex_doi(string):
    regex = re.compile(r"https:\/\/doi.org\/10.\d{4,9}\/[-._;()\/:a-zA-Z0-9]+")
    res = re.findall(regex, string)
    if res:
        return res[0]
    return "Could not find doi"


def get_doi(url, timeout=5):
    """
    get_doi('https://onlinelibrary.wiley.com/doi/abs/10.1111/1467-9817.12313')
    """
    # headers = {
    #     'User-Agent': 'Mozilla/5.0'
    # }
    try:
        s = Session()
        headers = OrderedDict(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                "dnt": "1",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36",
            }
        )
        # headers = OrderedDict({
        #     'Accept-Encoding': 'gzip, deflate, br',
        #     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:77.0) Gecko/20100101 Firefox/77.0'
        # })
        s.headers = headers
        res = s.get(url, headers=headers)
        # res = requests.get(
        #     url,
        #     headers=headers,
        #     timeout=timeout,
        #     allow_redirects=True
        # )
        status_code = res.status_code
        if status_code >= 200 and status_code < 400:
            content = soup(res.content, "lxml")
            dois = content.find_all(
                string=re.compile(
                    r"https:\/\/doi.org\/10.\d{4,9}\/[-._;()\/:a-zA-Z0-9]+"
                )
            )
            dois = list(map(str.strip, dois))
            dois = list(map(regex_doi, dois))
            doi_counter = Counter(dois)
            most_common_doi = doi_counter.most_common(1)

            if most_common_doi:
                doi = most_common_doi[0][0]
            else:
                doi = None
            return doi
        else:
            return "Timeout"
    except Exception as e:
        print(e)
        return e


"""
from manubot.cite.citekey import CiteKey, citekey_to_csl_item, url_to_citekey
from paper.manubot import RHCiteKey

url = 'https://library.seg.org/doi/10.1190/geo2020-0417.1'
citekey = url_to_citekey(url)
citekey = RHCiteKey(citekey)
csl_item = citekey_to_csl_item(citekey)
"""
