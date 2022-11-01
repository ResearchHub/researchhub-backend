import requests

from researchhub.settings import SERP_API_KEY

GOOGLE_SCHOLAR_PROFILES = "google_scholar_profiles"
GOOGLE_SCHOLAR_AUTHOR = "google_scholar_author"

ALLOWED_ENGINES = (
    GOOGLE_SCHOLAR_PROFILES,
    GOOGLE_SCHOLAR_AUTHOR,
)

# https://serpapi.com/search.json?engine=google_scholar_profiles&mauthors=GIAN+MARIA&hl=en&api_key=2f6cf9ba5aa10a940f4ef4ba4f46a0eda06e2a10d977191cf5d8dfb4754a530d
# https://serpapi.com/search.json?engine=google_scholar_author&author_id=8cOnY5YAAAAJ&hl=en&start=100&api_key=2f6cf9ba5aa10a940f4ef4ba4f46a0eda06e2a10d977191cf5d8dfb4754a530d


class Serp:
    def __init__(self, search_type=GOOGLE_SCHOLAR_AUTHOR, timeout=10):

        if search_type not in ALLOWED_ENGINES:
            raise Exception(f"Invalid search type: {search_type}")

        self.search_type = search_type
        self.base_url = f"https://serpapi.com/search.json?api_key={SERP_API_KEY}"
        self.engine_url = f"{self.base_url}&engine={search_type}"
        self.base_headers = {
            "User-Agent": "mailto:hello@researchhub.com",
            "From": "mailto:hello@researchhub.com",
        }
        self.timeout = timeout

    def get_author_from_id(self, google_author_id):
        if self.search_type != GOOGLE_SCHOLAR_AUTHOR:
            raise Exception(f"Invalid search type for this query: {self.search_type}")

        url = f"{self.engine_url}&author_id={google_author_id}"
        res = requests.get(url)
        res.raise_for_status()
        return res.json()
