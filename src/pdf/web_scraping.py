import requests

def init_zenrows():
    # Suppress only the single warning.
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def web_scrape(url: str, proxies: dict, verify: bool)-> requests.models.Response:
    '''wbb_scape scapes the given url (with optional proxy settings).
    '''
    return requests.get(url, proxies=proxies, verify=verify)
