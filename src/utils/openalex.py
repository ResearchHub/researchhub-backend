import datetime
import math
from unicodedata import normalize

from dateutil import parser
from django.utils.timezone import get_current_timezone, is_aware, make_aware

from paper.exceptions import DOINotFoundError
from paper.utils import check_url_contains_pdf, format_raw_authors
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

    def build_paper_from_openalex_work(self, work):
        doi = work.get("doi", work.get("ids", {}).get("doi", ""))
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

        url = primary_location.get("landing_page_url", None)

        title = normalize("NFKD", work.get("title", "") or "").strip()
        raw_authors = work.get("authorships", [])
        concepts = work.get("concepts", [])
        topics = work.get("topics", [])

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
            "external_source": source.get("display_name", None)
            or source.get("name", None)
            or source.get("publisher", None),
            "citations": work.get("cited_by_count", 0),
            "open_alex_raw_json": work,
            "openalex_id": work.get("id", None),
            "is_retracted": work.get("is_retracted", None),
            "mag_id": work.get("ids", {}).get("mag", None),
            "pubmed_id": work.get("ids", {}).get("pmid", None),
            "pubmed_central_id": work.get("ids", {}).get("pmcid", None),
            "work_type": work.get("type", None),
            "language": work.get("language", None),
        }

        locations = [work.get("primary_location", {})] + work.get("locations", [])
        for location in locations:
            if location.get("pdf_url", None):
                paper["pdf_url"] = location.get("pdf_url")
                break

        return paper, concepts, topics

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

    def get_institutions(self, next_cursor="*", page=1, batch_size=100):
        filters = {
            "page": page,
            "per-page": batch_size,
            "cursor": next_cursor,
        }

        response = self._get("institutions", filters=filters)
        institutions = response.get("results", [])

        next_cursor = response.get("meta", {}).get("next_cursor")
        cursor = next_cursor if next_cursor != "*" else None
        return institutions, cursor

    def get_topics(self, next_cursor="*", page=1, batch_size=100):
        filters = {
            "page": page,
            "per-page": batch_size,
            "cursor": next_cursor,
        }

        response = self._get("topics", filters=filters)
        topics = response.get("results", [])

        next_cursor = response.get("meta", {}).get("next_cursor")
        cursor = next_cursor if next_cursor != "*" else None
        return topics, cursor

    def get_authors(
        self,
        next_cursor="*",
        batch_size=100,
        openalex_ids=None,
    ):
        # Build the filter
        oa_filters = []

        if isinstance(openalex_ids, list):
            oa_filters.append(f"ids.openalex:{'|'.join(openalex_ids)}")

        filters = {
            "filter": ",".join(oa_filters),
            "per-page": batch_size,
            "cursor": next_cursor,
        }

        response = self._get("authors", filters=filters)
        authors = response.get("results", [])
        next_cursor = response.get("meta", {}).get("next_cursor")
        cursor = next_cursor if next_cursor != "*" else None
        return authors, cursor

    def get_work(
        self,
        openalex_id=None,
    ):
        return self._get(f"works/{openalex_id}")

    def get_works(
        self,
        since_date=None,
        types=None,
        next_cursor="*",
        batch_size=100,
        openalex_ids=None,
        source_id=None,
        openalex_author_id=None,
    ):
        """
        Fetches works from OpenAlex based on the given criteria.

        Works published on ResearchHub are filtered out (by DOI).
        """
        # Build the filter
        oa_filters = []
        if isinstance(types, list):
            oa_filters.append(f"type:{'|'.join(types)}")

        if source_id:
            oa_filters.append(f"primary_location.source.id:{source_id}")

        if since_date:
            # Format the date in YYYY-MM-DD format
            formatted_date = since_date.strftime("%Y-%m-%d")
            oa_filters.append(f"from_created_date:{formatted_date}")

        if isinstance(openalex_ids, list):
            oa_filters.append(f"ids.openalex:{'|'.join(openalex_ids)}")

        if openalex_author_id:
            oa_filters.append(f"author.id:{openalex_author_id}")

        filters = {
            "filter": ",".join(oa_filters),
            "per-page": batch_size,
            "cursor": next_cursor,
        }

        response = self._get("works", filters=filters)
        works = response.get("results", [])

        # Filter out works that were published on ResearchHub,
        # have a `researchhub` namespace in the DOI.
        filtered_works = list(
            filter(
                lambda w: "/researchhub." not in w.get("doi", ""),
                works,
            )
        )

        next_cursor = response.get("meta", {}).get("next_cursor")
        cursor = next_cursor if next_cursor != "*" else None
        return filtered_works, cursor

    @classmethod
    def normalize_dates(self, generic_openalex_object):
        """Normalize the dates of an OpenAlex object such that
        they include timezone information"""

        _generic_openalex_object = generic_openalex_object.copy()

        has_dates = _generic_openalex_object.get(
            "updated_date"
        ) and _generic_openalex_object.get("created_date")
        if has_dates:
            openalex_updated_date = parser.parse(
                _generic_openalex_object["updated_date"]
            )
            openalex_created_date = parser.parse(
                _generic_openalex_object["created_date"]
            )

            _generic_openalex_object["updated_date"] = openalex_updated_date
            _generic_openalex_object["created_date"] = openalex_created_date
            if not is_aware(openalex_updated_date):
                _generic_openalex_object["updated_date"] = make_aware(
                    _generic_openalex_object["updated_date"],
                    timezone=get_current_timezone(),
                )
            if not is_aware(openalex_created_date):
                _generic_openalex_object["created_date"] = make_aware(
                    _generic_openalex_object["created_date"],
                    timezone=get_current_timezone(),
                )

        return _generic_openalex_object
