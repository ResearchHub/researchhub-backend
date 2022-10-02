from paper.exceptions import DOINotFoundError
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

    # Fetch hydrated concepts by ids: https://docs.openalex.org/about-the-data/concept#id
    # e.g. https://openalex.org/C126537357
    # May come from local db or openalex api.
    # May raise HTTPError.
    def get_hydrated_concepts(self, concept_id_urls):
        stored_concepts = Concept.objects.filter(openalex_id__in=concept_id_urls)
        all_concepts_stored = stored_concepts.count() == len(concept_id_urls)
        no_concept_needs_refresh = all(not c.needs_refresh() for c in stored_concepts)
        if all_concepts_stored and no_concept_needs_refresh:
            concepts_by_id = {stored_concept.openalex_id: {
                "openalex_id": stored_concept.openalex_id,
                "display_name": stored_concept.display_name,
                "description": stored_concept.description,
                "openalex_created_date": stored_concept.openalex_created_date,
                "openalex_updated_date": stored_concept.openalex_updated_date
            } for stored_concept in stored_concepts}
        else:
            # e.g. https://openalex.org/C126537357 -> C126537357
            concept_ids = [concept_id_url.split("/")[-1] for concept_id_url in concept_id_urls]
            filters = {"filter": f"openalex_id:{'|'.join(concept_ids)}"}
            response = self._get("concepts", filters)
            api_concepts = response["results"]
            concepts_by_id = {concept["id"]: {
                "openalex_id": concept["id"],
                "display_name": concept["display_name"],
                "description": concept["description"] or "",
                "openalex_created_date": concept["created_date"],
                "openalex_updated_date": concept["updated_date"]
            } for concept in api_concepts}
        # preserve ordering from concept_id_urls
        return [concepts_by_id[concept_id_url] for concept_id_url in concept_id_urls]

