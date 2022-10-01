import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry


def retryable_requests_session(total_retries=3, backoff_factor=1, status_forcelist=None):
    retry_strategy = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist or [429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
