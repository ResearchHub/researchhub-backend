import datetime
import math

from paper.exceptions import DOINotFoundError
from paper.utils import check_url_contains_pdf, format_raw_authors
from unicodedata import normalize
from researchhub.settings import OPENALEX_KEY
from utils.aws import download_pdf
from utils.parsers import rebuild_sentence_from_inverted_index
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

    def _get_works_from_api_url(self, data):
        if isinstance(data, list):
            for result in data:
                self._get_works_from_api_url(result)
            return data
        elif isinstance(data, dict):
            works_api_url = data.get("works_api_url", None)
            if works_api_url:
                with retryable_requests_session() as session:
                    response = session.get(
                        works_api_url, headers=self.base_headers, timeout=self.timeout
                    )
                response.raise_for_status()
                data["works"] = response.json().get("results", [])
        return data

    def map_to_csl_format(self, input_json, mapping=None):
        """
        Maps fields in the input_json based on the given mapping.

        Args:
            input_json (dict): JSON whose fields need to be mapped.
            mapping (dict): Mapping of fields in input_json to desired fields.

        Returns:
            dict: JSON with mapped fields.
        """
        from citation.schema import OPENALEX_TO_CSL_FORMAT

        output_json = {}
        if not mapping:
            mapping = OPENALEX_TO_CSL_FORMAT

        for key, value in input_json.items():
            # Check if the current key is in the mapping
            if key in mapping:
                mapped_key = mapping[key]

                # If the mapped key is a dictionary, recursively apply mapping to the input JSON value
                if isinstance(mapped_key, dict) and isinstance(value, dict):
                    output_json.update(self.map_to_csl_format(value, mapped_key))
                elif "." in mapped_key:
                    # Split on the '.' and assign to a nested dictionary
                    outer_key, inner_key = mapped_key.split(".")
                    if outer_key not in output_json:
                        output_json[outer_key] = {}

                    if key == "pdf_url":
                        urls = download_pdf(value)

                    if urls:
                        output_json[outer_key][inner_key] = urls.get("url")
                        output_json["signed_pdf_url"] = urls.get("signed_url")

                    output_json[outer_key][inner_key] = value
                else:
                    if key == "abstract_inverted_index" or key == "abstract":
                        if isinstance(value, str):
                            output_json[mapped_key] = value
                        else:
                            output_json[
                                mapped_key
                            ] = rebuild_sentence_from_inverted_index(value)
                    else:
                        output_json[mapped_key] = value
            else:
                output_json[key] = value

        return output_json
    
    def parse_to_paper_format(self, work):
        doi = work.get("doi", work.get('ids', {}).get('doi', ''))
        if doi is None:
            raise DOINotFoundError(f"No DOI found for work: {work}")
        
        # remove https://doi.org/ from doi
        doi = doi.replace("https://doi.org/", "")

        primary_location = work.get("primary_location", {})
        if primary_location is None:
            primary_location = {}
        source = primary_location.get("source", {})
        if source is None:
            source = {}

        oa = work.get("open_access", {})
        if oa is None:
            oa = {}
        oa_pdf_url = oa.get("oa_url", None)

        url = primary_location.get("landing_page_url", None)

        title = normalize("NFKD", work.get("title", ""))
        raw_authors = work.get("authorships", [])
        concepts = work.get("concepts", [])

        pdf_license = primary_location.get("license", None)
        if pdf_license is None:
            pdf_license = work.get("license", None)

        abstract = rebuild_sentence_from_inverted_index(
            work.get("abstract_inverted_index", {})
        )

        paper = {
            "doi": doi,
            "url": url,
            "abstract": abstract,
            "raw_authors": format_raw_authors(raw_authors),
            "title": title,
            "paper_title": title,
            "alternate_ids": work.get("ids", {}),
            "paper_publish_date": work.get("publication_date", None),
            "is_open_access": oa.get("is_oa", None),
            "oa_status": oa.get("oa_status", None),
            "pdf_license": primary_location.get("license", None),
            "pdf_license_url": url,
            "retrieved_from_external_source": True,
            "external_source": source.get("display_name", None) or source.get("name", None) or source.get("publisher", None),
            "citations": work.get("cited_by_count", 0),
            "open_alex_raw_json": work,
        }

        if oa_pdf_url and check_url_contains_pdf(oa_pdf_url):
            paper["pdf_url"] = oa_pdf_url

        return paper, concepts

    def get_data_from_doi(self, doi):
        filters = {"filter": f"doi:{doi}"}
        works = self._get("works", filters)
        meta = works["meta"]
        count = meta["count"]
        results = works["results"]
        if count == 0:
            raise DOINotFoundError(f"No OpenAlex works found for doi: {doi}")
        return results[0]

    def get_data_from_id(self, openalex_id):
        filters = {
            "filter": f"author.id:{openalex_id}",
            "per-page": self.per_page,
            "page": 1,
        }
        works = self._get("works", filters)
        meta = works["meta"]
        count = meta["count"]
        results = works["results"]

        if count == 0:
            raise DOINotFoundError(
                f"No OpenAlex works found for OpenAlex Profile: {openalex_id}"
            )
        elif count > self.per_page:
            pages = math.ceil(count / self.per_page)
            for i in range(2, pages + 1):
                filters["page"] = i
                new_page_works = self._get("works", filters)
                results.extend(new_page_works["results"])
        return results

    def get_data_from_source(self, source, date=None, cursor="*"):
        oa_filter = f"locations.source.id:{source}"
        if date:
            oa_filter = f"locations.source.id:{source},from_created_date:{date}"
        filters = {
            "filter": oa_filter,
            "per-page": self.per_page,
            "cursor": cursor,
        }
        works = self._get("works", filters)
        return works

    def get_concepts(self, cursor="*"):
        filters = {"cursor": cursor}
        concepts = self._get("concepts", filters=filters)
        return concepts

    def get_author_via_orcid(self, orcid_id):
        orcid_lookup = f"https://orcid.org/{orcid_id}"
        res = self._get(f"authors/{orcid_lookup}")
        return res

    def search_authors_via_name(self, name, page=1):
        filters = {"search": name, "page": page, "per_page": 10}
        res = self._get("authors", filters=filters)
        return res

    # Hydrates a list of dehydrated paper concepts with fresh and expanded data from OpenAlex
    # https://docs.openalex.org/about-the-data/concept#id
    def hydrate_paper_concepts(self, paper_concepts):
        concept_ids = [concept["id"].split("/")[-1] for concept in paper_concepts]
        filters = {"filter": f"openalex_id:{'|'.join(concept_ids)}"}

        hydrated_concepts = []
        try:
            response = self._get("concepts", filters)
            api_concepts = response["results"]
            for hydrated_concept in api_concepts:
                paper_concept = next(
                    (
                        concept
                        for concept in paper_concepts
                        if concept["id"] == hydrated_concept["id"]
                    ),
                    None,
                )

                if not paper_concept:
                    continue

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
        except Exception as e:
            return []
        
    def get_new_works_batch(
        self, since_date, type="article", cursor="*",
        batch_size=100,
    ):
        """
        Get works published after the specified date.

        Args:
            since_date (datetime.date): Date to start searching for new papers.
            cursor (str): Pagination cursor for API requests.
            batch_size (int): Number of works to fetch in each request.

        Returns:
            list: List of new works since the given date.
            cursor (str): Pagination cursor for the next request.
        """
        # Format the date in YYYY-MM-DD format
        formatted_date = since_date.strftime("%Y-%m-%d")
        
        # Build the filter
        oa_filter = f"from_created_date:{formatted_date},type:{type}"
        filters = {
            "filter": oa_filter,
            "per-page": batch_size,
            "cursor": cursor,
        }

        response = self._get("works", filters=filters)
        works = response.get("results", [])
        next_cursor = response.get("meta", {}).get("next_cursor")
        cursor = next_cursor if next_cursor != "*" else None
        return works, cursor
