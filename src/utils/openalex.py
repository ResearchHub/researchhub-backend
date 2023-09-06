from paper.exceptions import DOINotFoundError
from researchhub.settings import OPENALEX_KEY
from tag.models import Concept
from utils.retryable_requests import retryable_requests_session


class OpenAlex:
    def __init__(self, timeout=10):
        self.base_url = "https://api.openalex.org"
        self.base_params = {"mailto": "hello@researchhub.com"}
        self.base_headers = {
            "User-Agent": "mailto:hello@researchhub.com",
            "From": "mailto:hello@researchhub.com",
        }
        self.timeout = timeout
        self.per_page = 25

        if OPENALEX_KEY:
            self.base_params["api_key"] = OPENALEX_KEY

    def _get(self, url, filters=None, headers=None):
        if not headers:
            headers = {}
        if not filters:
            filters = {}

        params = {**filters, **self.base_params}
        headers = {**headers, **self.base_headers}
        url = f"{self.base_url}/{url}"
        with retryable_requests_session() as session:
            response = session.get(
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

    # Hydrates a list of dehydrated paper concepts with fresh and expanded data from OpenAlex
    # https://docs.openalex.org/about-the-data/concept#id
    def hydrate_paper_concepts(self, paper_concepts):
        concept_ids = [concept["id"].split("/")[-1] for concept in paper_concepts]
        filters = {"filter": f"openalex_id:{'|'.join(concept_ids)}"}
        response = self._get("concepts", filters)
        api_concepts = response["results"]

        hydrated_concepts = []
        for hydrated_concept in api_concepts:
            paper_concept = next(
                (
                    concept
                    for concept in paper_concepts
                    if concept["id"] == hydrated_concept["id"]
                ),
                None,
            )

            hydrated_concepts.append(
                {
                    "level": paper_concept["level"],
                    "score": paper_concept["score"],
                    "openalex_id": hydrated_concept["id"],
                    "display_name": hydrated_concept["display_name"],
                    "description": hydrated_concept["description"] or "",
                    "openalex_created_date": hydrated_concept["created_date"],
                    "openalex_updated_date": hydrated_concept["updated_date"],
                }
            )

        return hydrated_concepts
