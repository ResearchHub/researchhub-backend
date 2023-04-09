import requests

# NOTE(kevin.yang):
# For web scraping, we use zenrows (for now).
# Other alternative includes scrapeops, etc.
#
# NOTE(kevin.yang): This is currently my personal account (testing only), replace it with paid production account.
ZENROWS_PROXY = "http://a41b950f3879ea357ef43260361127ca9e802c9c:@proxy.zenrows.com:8001"
ZENROWS_PROXIES = {"http": ZENROWS_PROXY, "https": ZENROWS_PROXY}

def init_zenrows():
    # Suppress only the single warning.
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def web_scrape(url: str, proxies: dict, verify: bool)-> requests.models.Response:
    '''wbb_scape scapes the given url (with optional proxy settings).
    '''
    return requests.get(url, proxies=proxies, verify=verify)
