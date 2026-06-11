import math
import re
from dataclasses import dataclass
from unicodedata import normalize

from dateutil import parser
from django.utils.timezone import get_current_timezone, is_aware, make_aware

from paper.exceptions import DOINotFoundError
from paper.utils import format_raw_authors
from researchhub.settings import OPENALEX_KEY
from utils.parsers import rebuild_sentence_from_inverted_index
from utils.retryable_requests import retryable_requests_session

SOURCE_TO_OPENALEX_ID = {
    "BIORXIV": "s4306402567",
    "MEDRXIV": "s4306400573",
    "ARXIV": "s4306400194",
    "CHEMRXIV": "s3005989158",
    "RESEARCH_SQUARE": "s4306402450",
    "OSF": "s4306401127",
    "PEERJ": "s1983995261",
    "AUTHOREA": "s4306402105",
    "SSRN": "s4210172589",
}


def normalize_openalex_id(value: str | None) -> str:
    """Bare OpenAlex id (e.g. ``A5023888391``) from a full URL or an already-bare id.

    Returns ``""`` when there is nothing to normalize. Case is preserved, so
    lowercase both sides when comparing ids.
    """
    s = str(value or "").strip()
    if "openalex.org/" in s:
        s = s.rstrip("/").rsplit("/", 1)[-1]
    return s.strip("/")


_ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dxX])")
_OPENALEX_AUTHOR_RE = re.compile(r"openalex\.org/(A\d+)", re.IGNORECASE)


def scholarly_ids_from_urls(urls) -> tuple[str | None, str | None]:
    """Mine an ORCID and/or OpenAlex author id from a list of URLs.

    Returns ``(orcid, openalex_author_id)``, each ``None`` when absent. ORCID is
    only ever a lookup key into OpenAlex's ``/authors`` endpoint here.
    """
    orcid: str | None = None
    oa_id: str | None = None
    for url in urls or []:
        if orcid is None and "orcid.org" in url.lower():
            m = _ORCID_RE.search(url)
            if m:
                orcid = m.group(1).upper()
        if oa_id is None:
            m = _OPENALEX_AUTHOR_RE.search(url)
            if m:
                oa_id = m.group(1)
    return orcid, oa_id


def author_institution_names(entity: dict) -> list[str]:
    """Institution display names found anywhere on an OpenAlex author entity."""
    names: list[str] = []
    for inst in entity.get("last_known_institutions") or []:
        dn = (inst or {}).get("display_name")
        if dn:
            names.append(dn)
    for aff in entity.get("affiliations") or []:
        inst = (aff or {}).get("institution") or {}
        if inst.get("display_name"):
            names.append(inst["display_name"])
    return names


@dataclass
class Author:
    """An OpenAlex author entity, reduced to the fields profile-building uses.

    ``metrics`` keeps the entity's citation stats under stable keys (note
    ``2yr_mean_citedness`` becomes ``two_year_mean_citedness``) plus the
    author URL as ``source_url``; it is ``{}`` when the entity carries no
    stats at all. ``affiliations`` and ``topics`` are deduped display names,
    uncapped -- callers apply their own limits.
    """

    id: str | None
    display_name: str | None
    metrics: dict
    affiliations: list[str]
    topics: list[str]

    @classmethod
    def from_openalex(cls, entity: dict):
        return cls(
            id=entity.get("id"),
            display_name=entity.get("display_name"),
            metrics=cls._metrics(entity),
            affiliations=cls._affiliations(entity),
            topics=cls._topics(entity),
        )

    @staticmethod
    def _metrics(entity: dict) -> dict:
        ss = entity.get("summary_stats") or {}
        metrics = {
            "h_index": ss.get("h_index"),
            "i10_index": ss.get("i10_index"),
            "two_year_mean_citedness": ss.get("2yr_mean_citedness"),
            "works_count": entity.get("works_count"),
            "cited_by_count": entity.get("cited_by_count"),
        }
        if all(v is None for v in metrics.values()):
            return {}
        metrics["source_url"] = entity.get("id")
        return metrics

    @staticmethod
    def _affiliations(entity: dict) -> list[str]:
        out: list[str] = []
        for name in author_institution_names(entity):
            name = (name or "").strip()
            if name and name not in out:
                out.append(name)
        return out

    @staticmethod
    def _topics(entity: dict) -> list[str]:
        """Topic display names, falling back to ``x_concepts`` when empty."""
        out: list[str] = []
        for source in (entity.get("topics") or [], entity.get("x_concepts") or []):
            for item in source:
                label = ((item or {}).get("display_name") or "").strip()
                if label and label not in out:
                    out.append(label)
            if out:
                break
        return out


@dataclass
class Work:
    """An OpenAlex work entity, reduced to the fields profile-building uses.

    ``author_position`` is one author's position ("first" | "middle" | "last")
    on the work, resolved against the ``author_id`` given at construction
    (``None`` when that author is not matched on the work).
    """

    title: str
    year: str
    source_url: str
    author_position: str | None = None

    @classmethod
    def from_openalex(cls, entity: dict, *, author_id: str | None = None):
        """Build a ``Work`` from an OpenAlex work entity.

        Returns ``None`` for unusable entities: no title, or neither a DOI nor
        an OpenAlex URL to cite as the source.
        """
        title = str(entity.get("display_name") or "").strip()
        if not title:
            return None
        url = (
            str(entity.get("doi") or "").strip() or str(entity.get("id") or "").strip()
        )
        if not url:
            return None
        return cls(
            title=title,
            year=str(entity.get("publication_year") or "").strip(),
            source_url=url,
            author_position=cls._author_position(entity, author_id),
        )

    @staticmethod
    def _author_position(entity: dict, author_id: str | None) -> str | None:
        target = normalize_openalex_id(author_id).lower()
        if not target:
            return None
        for authorship in entity.get("authorships") or []:
            author = (authorship or {}).get("author") or {}
            if normalize_openalex_id(author.get("id")).lower() == target:
                return authorship.get("author_position") or None
        return None

    @property
    def is_lead_author(self) -> bool:
        return self.author_position in ("first", "last")

    @property
    def year_int(self) -> int:
        try:
            return int(self.year)
        except ValueError:
            return 0

    @property
    def label(self) -> str:
        label = f"({self.year}) {self.title}" if self.year else self.title
        if self.is_lead_author:
            label += f" [{self.author_position} author]"
        return label

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "year": self.year,
            "source_url": self.source_url,
            "author_position": self.author_position,
        }


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

    def get_author(self, openalex_id):
        """Fetch a single author entity by its OpenAlex id (e.g. ``A5023888391``)."""
        return self._get(f"authors/{openalex_id}")

    def search_authors_via_name(self, name, page=1, institution_id=None):
        filters = {"search": name, "page": page, "per_page": 10}
        if institution_id:
            filters["filter"] = f"affiliations.institution.id:{institution_id}"
        res = self._get("authors", filters=filters)
        return res

    def search_institutions(self, query, page=1):
        filters = {"search": query, "page": page, "per_page": 5}
        return self._get("institutions", filters=filters)

    # Hydrates a list of dehydrated paper concepts with fresh and expanded data from
    # OpenAlex
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
        except Exception:
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
        source=None,
        openalex_author_id=None,
        from_updated_date=None,
        core_sources_only: bool = False,
        require_abstracts_and_authors: bool = False,
        sort=None,
    ):
        """
        Fetches works from OpenAlex based on the given criteria.

        Works published on ResearchHub are filtered out (by DOI).

        Args:
            core_sources_only (bool): If True, only fetch works from "core sources".
            require_abstracts_and_authors (bool): If True, only fetch works that have
                abstracts and authors.
            sort (str): OpenAlex sort expression, e.g. "publication_date:desc".
        """
        # Build the filter
        oa_filters = []
        if isinstance(types, list):
            oa_filters.append(f"type:{'|'.join(types)}")

        source_id = None
        if source:
            source_id = SOURCE_TO_OPENALEX_ID.get(source)
            if source_id is None:
                raise ValueError(f"Invalid source: {source}")

        if source_id:
            oa_filters.append(f"primary_location.source.id:{source_id}")

        if core_sources_only:
            # Only fetch works that are from "core sources".
            # See: https://docs.openalex.org/api-entities/sources/source-object#is_core
            oa_filters.append("primary_location.source.is_core:true")

        if require_abstracts_and_authors:
            # Only fetch works that have abstracts and authors
            oa_filters.append("has_abstract:true")
            oa_filters.append("authors_count:>0")

        if since_date:
            # Format the date in YYYY-MM-DD format
            formatted_date = since_date.strftime("%Y-%m-%d")
            oa_filters.append(f"from_created_date:{formatted_date}")

        if from_updated_date:
            # Format the date in YYYY-MM-DD format
            formatted_date = from_updated_date.strftime("%Y-%m-%d")
            oa_filters.append(f"from_updated_date:{formatted_date}")

        if isinstance(openalex_ids, list):
            oa_filters.append(f"ids.openalex:{'|'.join(openalex_ids)}")

        if openalex_author_id:
            oa_filters.append(f"author.id:{openalex_author_id}")

        filters = {
            "filter": ",".join(oa_filters),
            "per-page": batch_size,
            "cursor": next_cursor,
        }
        if sort:
            filters["sort"] = sort

        response = self._get("works", filters=filters)
        works = response.get("results", [])

        # Filter out works that were published on ResearchHub,
        # have a `researchhub` namespace in the DOI.
        filtered_works = list(
            filter(
                lambda w: (
                    w.get("doi") is None
                    or "/researchhub." not in w.get("doi", "").lower()
                ),
                works,
            )
        )

        next_cursor = response.get("meta", {}).get("next_cursor")
        cursor = next_cursor if next_cursor != "*" else None
        return filtered_works, cursor

    def get_works_typed(self, **kwargs) -> list[Work]:
        """Typed variant of :meth:`get_works`: parsed ``Work`` objects for one page.

        Forwards every keyword argument to ``get_works`` and maps each raw entity
        to a ``Work``, dropping unusable ones (no title, or no DOI/OpenAlex URL).
        ``author_position`` is attributed to ``openalex_author_id`` when given.

        The pagination cursor is intentionally not returned: this is for
        single-page, select-and-keep use, not full pagination.
        """
        author_id = kwargs.get("openalex_author_id")
        results, _ = self.get_works(**kwargs)
        works = []
        for entity in results or []:
            work = Work.from_openalex(entity, author_id=author_id)
            if work is not None:
                works.append(work)
        return works

    def autocomplete_works(self, query):
        """
        Search for works using OpenAlex's autocomplete endpoint.
        Returns suggestions for works matching the query.
        Only returns results that have a DOI.
        """
        filters = {
            "q": query,
            "filter": "has_doi:true,type:preprint|review|article",
        }  # Only return works that have a DOI
        return self._get("autocomplete/works", filters=filters)

    def get_work_by_doi(self, doi):
        """
        Fetch a work from OpenAlex using its DOI.
        Returns None if no work is found.
        """
        filters = {"filter": f"doi:{doi}"}
        response = self._get("works", filters=filters)
        results = response.get("results", [])
        return results[0] if results else None

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
