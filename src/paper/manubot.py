import logging
from functools import cached_property
from typing import Any, Dict

from manubot.cite.citekey import CiteKey
from manubot.cite.csl_item import CSL_Item
from manubot.cite.url import get_url_csl_item_manual, get_url_csl_item_zotero

CSLItem = Dict[str, Any]

url_retrievers = [
    get_url_csl_item_zotero,
    get_url_csl_item_manual,
]


class RHCiteKey(CiteKey):
    """
    Source: https://github.com/manubot/manubot/blob/main/manubot/cite/citekey.py#L17
    Modified so that get_url_csl_item won't use greycite (extremely slow)
    """

    # @cached_property
    @property
    def csl_item(self):
        csl_item = self.get_url_csl_item(self.standard_accession)
        if not isinstance(csl_item, CSL_Item):
            csl_item = CSL_Item(csl_item)
        csl_item.set_id(self.standard_id)
        return csl_item

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


"""
from manubot.cite.citekey import CiteKey, citekey_to_csl_item, url_to_citekey
from paper.manubot import RHCiteKey

url = 'https://library.seg.org/doi/10.1190/geo2020-0417.1'
citekey = url_to_citekey(url)
citekey = RHCiteKey(citekey)
csl_item = citekey_to_csl_item(citekey)
"""
