import requests

from paper.exceptions import DOINotFoundError


class OpenAlex:
    def __init__(self, timeout=10):
        self.base_url = "https://api.openalex.org"
        self.base_params = {"mailto": "hello@researchhub.com"}
        self.base_headers = {
            "User-Agent": "mailto:hello@researchhub.com",
            "From": "mailto:hello@researchhub.com",
        }
        self.timeout = timeout

    def _get(self, url, filters=None, headers=None):
        if not headers:
            headers = {}
        if not filters:
            filters = {}

        params = {**filters, **self.base_params}
        headers = {**headers, **self.base_headers}
        url = f"{self.base_url}/{url}"
        response = requests.get(
            url, params=params, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def get_data_from_doi(self, doi):
        filters = {"filter": f"doi:{doi}"}
        works = self._get("works", filters)
        meta = works["meta"]
        count = meta["count"]
        results = works["results"]
        if count == 0:
            raise DOINotFoundError(f"No OpenAlex works found for doi: {doi}")
        return results[0]

    # fetch a hydrated concept by id: https://docs.openalex.org/about-the-data/concept#id
    def get_hydrated_concept(self, concept_id_url):
        # e.g. https://api.openalex.org/concepts/C126537357 -> C126537357
        concept_id = concept_id_url.split("/")[-1]
        concept = self._get(f"concepts/{concept_id}")
        return {
            "openalex_id":           concept["id"],
            "display_name":          concept["display_name"],
            "description":           concept["description"],
            "openalex_created_date": concept["created_date"],
            "openalex_updated_date": concept["updated_date"]
        }