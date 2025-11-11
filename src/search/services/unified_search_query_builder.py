from dataclasses import dataclass
from typing import Any

from opensearchpy import Q

from utils.doi import DOI


@dataclass
class FieldConfig:

    name: str
    boost: float = 1.0
    query_types: list[str] | None = None

    def get_boosted_name(self) -> str:
        """Return field name with boost suffix."""
        if self.boost == 1.0:
            return self.name
        return f"{self.name}^{self.boost}"


class DocumentQueryBuilder:

    # Field configurations
    TITLE_FIELDS = [
        FieldConfig(
            "paper_title", boost=5.0, query_types=["phrase", "prefix", "fuzzy"]
        ),
        FieldConfig("title", boost=5.0, query_types=["phrase", "prefix", "fuzzy"]),
    ]

    AUTHOR_FIELDS = [
        FieldConfig("raw_authors.full_name", boost=3.0, query_types=["cross_fields"]),
        FieldConfig("authors.full_name", boost=3.0, query_types=["cross_fields"]),
    ]

    CONTENT_FIELDS = [
        FieldConfig("abstract", boost=2.0, query_types=["phrase", "fuzzy"]),
        FieldConfig("renderable_text", boost=1.0, query_types=["fuzzy"]),
    ]

    def __init__(self, query: str):
        """Initialize builder with search query."""
        self.query = query
        self.should_clauses: list[Q] = []
        self._add_doi_match_if_applicable()

    def _add_doi_match_if_applicable(self):
        """Add DOI exact match if query is a DOI."""
        try:
            if DOI.is_doi(self.query):
                normalized_doi = DOI.normalize_doi(self.query)
                self.should_clauses.append(
                    Q("term", doi={"value": normalized_doi, "boost": 8.0})
                )
        except Exception:
            pass

    def add_author_title_combination_strategy(self) -> "DocumentQueryBuilder":
        """Add strategy that requires author and title to co-occur."""
        author_fields = [field.get_boosted_name() for field in self.AUTHOR_FIELDS]
        title_fields = [field.get_boosted_name() for field in self.TITLE_FIELDS]

        combo_query = Q(
            "constant_score",
            filter=Q(
                "bool",
                must=[
                    Q(
                        "multi_match",
                        query=self.query,
                        type="cross_fields",
                        operator="or",
                        fields=author_fields,
                    ),
                    Q(
                        "multi_match",
                        query=self.query,
                        type="best_fields",
                        operator="and",
                        fields=title_fields,
                    ),
                ],
            ),
            boost=4.0,
        )
        self.should_clauses.append(combo_query)
        return self

    def add_phrase_strategy(
        self, fields: list[FieldConfig], slop: int = 1, boost_multiplier: float = 1.0
    ) -> "DocumentQueryBuilder":
        """Add phrase match strategy for specified fields."""
        queries = []
        for field in fields:
            if "phrase" in (field.query_types or []):
                # Abstract gets slop=2, titles get slop=1
                field_slop = 2 if field.name == "abstract" else slop
                # Abstract gets boost=1.5 (0.75 multiplier),
                # titles get boost=3.0 (0.6 multiplier)
                if field.name == "abstract":
                    field_boost = field.boost * 0.75
                else:
                    field_boost = field.boost * boost_multiplier
                queries.append(
                    Q(
                        "match_phrase",
                        **{
                            field.name: {
                                "query": self.query,
                                "slop": field_slop,
                                "boost": field_boost,
                            }
                        },
                    )
                )

        if queries:
            phrase_query = Q("dis_max", queries=queries, tie_breaker=0.1)
            self.should_clauses.append(phrase_query)
        return self

    def add_prefix_strategy(
        self,
        fields: list[FieldConfig],
        max_expansions: int = 20,
        boost_multiplier: float = 1.0,
    ) -> "DocumentQueryBuilder":
        """Add phrase prefix strategy for specified fields."""
        queries = []
        for field in fields:
            if "prefix" in (field.query_types or []):
                queries.append(
                    Q(
                        "match_phrase_prefix",
                        **{
                            field.name: {
                                "query": self.query,
                                "max_expansions": max_expansions,
                                "boost": field.boost * boost_multiplier,
                            }
                        },
                    )
                )

        if queries:
            prefix_query = Q("dis_max", queries=queries, tie_breaker=0.1)
            self.should_clauses.append(prefix_query)
        return self

    def add_fuzzy_strategy(
        self,
        fields: list[FieldConfig],
        operator: str = "and",
        boost_multiplier: float = 1.0,
    ) -> "DocumentQueryBuilder":
        """Add fuzzy match strategy for specified fields."""
        field_list = []
        for field in fields:
            if "fuzzy" in (field.query_types or []):
                # Fuzzy strategy uses different boosts:
                # - Titles: 4.0 (from 5.0 base)
                # - Authors: 2.0 (from 3.0 base)
                # - Abstract: 2.0 (same)
                # - Renderable text: 1.0 (same)
                if field.name in ["paper_title", "title"]:
                    fuzzy_boost = 4.0
                elif "authors" in field.name:
                    fuzzy_boost = 2.0
                else:
                    fuzzy_boost = field.boost * boost_multiplier

                if fuzzy_boost == 1.0:
                    boosted_name = field.name
                elif fuzzy_boost == int(fuzzy_boost):
                    boosted_name = f"{field.name}^{int(fuzzy_boost)}"
                else:
                    boosted_name = f"{field.name}^{fuzzy_boost}"
                field_list.append(boosted_name)

        if field_list:
            fuzzy_query = Q(
                "multi_match",
                query=self.query,
                fields=field_list,
                type="best_fields",
                fuzziness="AUTO",
                operator=operator,
            )
            self.should_clauses.append(fuzzy_query)
        return self

    def build(self) -> Q:
        return Q("bool", should=self.should_clauses, minimum_should_match=1)


class PersonQueryBuilder:

    def __init__(self, query: str):
        self.query = query

    def build(self) -> Q:
        return Q(
            "multi_match",
            query=self.query,
            fields=[
                "full_name^5",
                "first_name^3",
                "last_name^3",
                "headline^2",
                "description^1",
            ],
            type="best_fields",
            fuzziness="AUTO",
            operator="or",
        )


class UnifiedSearchQueryBuilder:

    def build_document_query(self, query: str) -> Q:

        builder = (
            DocumentQueryBuilder(query)
            .add_author_title_combination_strategy()
            .add_phrase_strategy(
                DocumentQueryBuilder.TITLE_FIELDS + DocumentQueryBuilder.CONTENT_FIELDS,
                slop=1,
                boost_multiplier=0.6,  # Reduce boosts (5.0 -> 3.0)
            )
            .add_prefix_strategy(
                DocumentQueryBuilder.TITLE_FIELDS, boost_multiplier=0.5
            )
            .add_fuzzy_strategy(
                DocumentQueryBuilder.TITLE_FIELDS
                + DocumentQueryBuilder.AUTHOR_FIELDS
                + DocumentQueryBuilder.CONTENT_FIELDS,
                boost_multiplier=1.0,  # Boosts handled per-field in add_fuzzy_strategy
            )
        )
        return builder.build()

    def build_person_query(self, query: str) -> Q:

        builder = PersonQueryBuilder(query)
        return builder.build()

    def build_rescore_query(self, query: str) -> dict[str, Any]:

        return {
            "window_size": 100,
            "query": {
                "rescore_query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "type": "cross_fields",
                                    "fields": [
                                        "raw_authors.full_name^2",
                                        "authors.full_name^2",
                                    ],
                                }
                            },
                            {
                                "multi_match": {
                                    "query": query,
                                    "type": "best_fields",
                                    "fields": ["paper_title^3", "title^3"],
                                }
                            },
                        ]
                    }
                },
                "query_weight": 0.9,
                "rescore_query_weight": 0.1,
            },
        }
