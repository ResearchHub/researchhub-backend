"""
OpenAlex Data Transfer Objects (DTOs)

This module defines dataclasses that represent the data structures returned by the OpenAlex API.
These DTOs provide:
1. Type safety for OpenAlex data
2. Clear documentation of expected data structures
3. Conversion methods between raw API data and structured objects

Usage:
    from utils.openalex_dto import OpenAlexWork, OpenAlexAuthor

    # Convert raw API data to DTO
    work = OpenAlexWork.from_dict(raw_work_data)
    print(work.title)  # Type-safe access with auto-completion
"""

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class OpenAlexConcept:
    """Represents an OpenAlex concept (e.g., a research topic)"""

    id: str
    display_name: str
    level: int
    score: float
    wikidata_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAlexConcept":
        """Create a concept from OpenAlex API data"""
        return cls(
            id=data.get("id", ""),
            display_name=data.get("display_name", ""),
            level=data.get("level", 0),
            score=data.get("score", 0.0),
            wikidata_id=data.get("wikidata_id"),
        )


@dataclass
class OpenAlexAuthorInstitution:
    """Represents an institution affiliated with an author"""

    id: str
    display_name: str
    type: Optional[str] = None
    country_code: Optional[str] = None
    years: List[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAlexAuthorInstitution":
        """Create an institution from OpenAlex API data"""
        institution = data.get("institution", {})
        return cls(
            id=institution.get("id", ""),
            display_name=institution.get("display_name", ""),
            type=institution.get("type"),
            country_code=institution.get("country_code"),
            years=data.get("years", []),
        )


@dataclass
class OpenAlexAuthor:
    """Represents an OpenAlex author"""

    id: str
    display_name: str
    orcid_id: Optional[str] = None
    works_count: int = 0
    cited_by_count: int = 0
    h_index: Optional[int] = None
    i10_index: Optional[int] = None
    two_year_mean_citedness: Optional[float] = None
    affiliations: List[OpenAlexAuthorInstitution] = field(default_factory=list)
    counts_by_year: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAlexAuthor":
        """Create an author from OpenAlex API data"""
        summary_stats = data.get("summary_stats", {})

        # Process affiliations
        affiliations = []
        for affiliation_data in data.get("affiliations", []):
            if not affiliation_data.get("institution"):
                continue
            affiliations.append(OpenAlexAuthorInstitution.from_dict(affiliation_data))

        return cls(
            id=data.get("id", ""),
            display_name=data.get("display_name", ""),
            orcid_id=data.get("orcid"),
            works_count=data.get("works_count", 0),
            cited_by_count=data.get("cited_by_count", 0),
            h_index=summary_stats.get("h_index"),
            i10_index=summary_stats.get("i10_index"),
            two_year_mean_citedness=summary_stats.get("2yr_mean_citedness"),
            affiliations=affiliations,
            counts_by_year=data.get("counts_by_year", []),
        )


@dataclass
class OpenAlexAuthorship:
    """Represents an authorship relationship in an OpenAlex work"""

    author_position: str
    is_corresponding: bool
    author_id: str
    author_display_name: str
    institutions: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAlexAuthorship":
        """Create an authorship from OpenAlex API data"""
        return cls(
            author_position=data.get("author_position", ""),
            is_corresponding=data.get("is_corresponding", False),
            author_id=data.get("author", {}).get("id", ""),
            author_display_name=data.get("author", {}).get("display_name", ""),
            institutions=data.get("institutions", []),
        )


@dataclass
class OpenAlexWorkTopic:
    """Represents a topic associated with an OpenAlex work"""

    id: str
    display_name: str
    score: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAlexWorkTopic":
        """Create a topic from OpenAlex API data"""
        return cls(
            id=data.get("id", ""),
            display_name=data.get("display_name", ""),
            score=data.get("score", 0.0),
        )


@dataclass
class OpenAlexWork:
    """Represents an OpenAlex work (paper, article, etc.)"""

    id: str
    title: str
    doi: Optional[str] = None
    publication_date: Optional[datetime.date] = None
    publication_year: Optional[int] = None
    abstract: Optional[str] = None
    cited_by_count: int = 0
    is_open_access: bool = False
    oa_status: Optional[str] = None
    type: Optional[str] = None
    is_retracted: bool = False
    language: Optional[str] = None
    authorships: List[OpenAlexAuthorship] = field(default_factory=list)
    concepts: List[OpenAlexConcept] = field(default_factory=list)
    topics: List[OpenAlexWorkTopic] = field(default_factory=list)
    is_authors_truncated: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAlexWork":
        """Create a work from OpenAlex API data"""
        # Parse publication date
        publication_date = None
        if publication_date_str := data.get("publication_date"):
            try:
                publication_date = datetime.datetime.strptime(
                    publication_date_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                pass

        # Process authorships
        authorships = []
        for authorship_data in data.get("authorships", []):
            authorships.append(OpenAlexAuthorship.from_dict(authorship_data))

        # Process concepts
        concepts = []
        for concept_data in data.get("concepts", []):
            concepts.append(OpenAlexConcept.from_dict(concept_data))

        # Process topics
        topics = []
        for topic_data in data.get("topics", []):
            topics.append(OpenAlexWorkTopic.from_dict(topic_data))

        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            doi=data.get("doi"),
            publication_date=publication_date,
            publication_year=data.get("publication_year"),
            abstract=data.get("abstract"),
            cited_by_count=data.get("cited_by_count", 0),
            is_open_access=data.get("is_open_access", False),
            oa_status=data.get("oa_status"),
            type=data.get("type"),
            is_retracted=data.get("is_retracted", False),
            language=data.get("language"),
            authorships=authorships,
            concepts=concepts,
            topics=topics,
            is_authors_truncated=data.get("is_authors_truncated", False),
        )

    def to_paper_dict(self) -> Dict[str, Any]:
        """Convert OpenAlex work to ResearchHub paper format"""
        return {
            "paper_title": self.title,
            "title": self.title,
            "doi": self.doi,
            "paper_publish_date": self.publication_date,
            "abstract": self.abstract,
            "citations": self.cited_by_count,
            "is_open_access": self.is_open_access,
            "oa_status": self.oa_status,
            "work_type": self.type,
            "is_retracted": self.is_retracted,
            "language": self.language,
            "openalex_id": self.id,
            "retrieved_from_external_source": True,
        }
