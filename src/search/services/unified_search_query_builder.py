"""Query builders for unified search."""

import math

from opensearchpy import Q

from search.services.search_config import (
    DEFAULT_DOCUMENT_CONFIG,
    DEFAULT_PERSON_CONFIG,
    DocumentSearchConfig,
    FieldConfig,
    PersonSearchConfig,
)
from utils.doi import DOI


class DocumentQueryBuilder:
    """Builds OpenSearch queries for document (paper/post) search."""

    def __init__(self, query: str, config: DocumentSearchConfig | None = None):
        self.query = query
        self.config = config or DEFAULT_DOCUMENT_CONFIG
        self._query_terms: list[str] = [w for w in (query or "").split() if w]
        self.should_clauses: list[Q] = []
        self._add_doi_match_if_applicable()

    @staticmethod
    def _is_single_word_query(query: str) -> bool:
        return len(query.strip().split()) == 1

    @staticmethod
    def _limit_query_to_max_words(query: str, max_words: int) -> str:
        words = query.split()
        return query if len(words) <= max_words else " ".join(words[:max_words])

    def _format_boosted_field_name(self, field_name: str, boost: float) -> str:
        if math.isclose(boost, 1.0):
            return field_name
        if math.isclose(boost, round(boost)):
            return f"{field_name}^{int(round(boost))}"
        return f"{field_name}^{boost}"

    def _is_short_enough_for_fuzzy_content(self) -> bool:
        return len(self._query_terms) <= self.config.max_terms_for_fuzzy_content_fields

    def _get_field_category(self, field: FieldConfig) -> str:
        if field.name in ["paper_title", "title"]:
            return "title"
        if "authors" in field.name:
            return "author"
        return "content"

    def _get_simple_match_boost(self, category: str) -> float:
        if category == "title":
            return self.config.simple_match_title_boost
        if category == "author":
            return self.config.simple_match_author_boost
        return self.config.simple_match_content_boost

    def _get_phrase_boost(self, field: FieldConfig) -> float:
        if field.name == "abstract":
            return self.config.phrase_abstract_boost
        category = self._get_field_category(field)
        if category == "title":
            return self.config.phrase_title_boost
        return self.config.phrase_content_boost

    def _get_fuzzy_boost(self, field: FieldConfig) -> float:
        if field.name in ["paper_title", "title"]:
            return self.config.fuzzy_title_boost
        if "authors" in field.name:
            return self.config.fuzzy_author_boost
        return field.boost

    def _add_doi_match_if_applicable(self):
        try:
            if DOI.is_doi(self.query):
                normalized_doi = DOI.normalize_doi(self.query)
                self.should_clauses.append(
                    Q(
                        "term",
                        doi={"value": normalized_doi, "boost": self.config.doi_boost},
                    )
                )
        except Exception:
            pass

    def add_author_title_combination_strategy(self) -> "DocumentQueryBuilder":
        truncated_query = self._limit_query_to_max_words(
            self.query, self.config.max_query_words_for_author_title_combo
        )

        author_fields = [f.get_boosted_name() for f in self.config.author_fields]
        title_fields = [f.get_boosted_name() for f in self.config.title_fields]

        author_queries = [
            Q("match", **{f.name: {"query": truncated_query, "operator": "or"}})
            for f in self.config.author_fields
        ]
        title_queries = [
            Q("match", **{f.name: {"query": truncated_query, "operator": "or"}})
            for f in self.config.title_fields
        ]

        if author_queries and title_queries:
            author_match = Q("bool", should=author_queries, minimum_should_match=1)
            title_match = Q("bool", should=title_queries, minimum_should_match=1)
            self.should_clauses.append(
                Q(
                    "bool",
                    must=[author_match, title_match],
                    boost=self.config.author_title_combo_boost,
                )
            )

        self.should_clauses.append(
            Q(
                "multi_match",
                query=self.query,
                type="cross_fields",
                operator="or",
                fields=author_fields + title_fields,
                boost=self.config.cross_field_combo_boost,
            )
        )
        return self

    def add_phrase_strategy(
        self, fields: list[FieldConfig], slop: int | None = None
    ) -> "DocumentQueryBuilder":
        if slop is None:
            slop = self.config.phrase_default_slop

        queries = []
        for field in fields:
            if "phrase" not in (field.query_types or []):
                continue
            field_slop = (
                self.config.phrase_abstract_slop if field.name == "abstract" else slop
            )
            queries.append(
                Q(
                    "match_phrase",
                    **{
                        field.name: {
                            "query": self.query,
                            "slop": field_slop,
                            "boost": field.boost * self._get_phrase_boost(field),
                        }
                    },
                )
            )

        if queries:
            self.should_clauses.append(
                Q(
                    "dis_max",
                    queries=queries,
                    tie_breaker=self.config.dis_max_tie_breaker,
                )
            )
        return self

    def add_prefix_strategy(
        self, fields: list[FieldConfig], max_expansions: int | None = None
    ) -> "DocumentQueryBuilder":
        if max_expansions is None:
            max_expansions = self.config.prefix_max_expansions_multi_word

        queries = []
        for field in fields:
            if "prefix" not in (field.query_types or []):
                continue
            queries.append(
                Q(
                    "match_phrase_prefix",
                    **{
                        field.name: {
                            "query": self.query,
                            "max_expansions": max_expansions,
                            "boost": field.boost * self.config.prefix_boost,
                        }
                    },
                )
            )

        if queries:
            self.should_clauses.append(
                Q(
                    "dis_max",
                    queries=queries,
                    tie_breaker=self.config.dis_max_tie_breaker,
                )
            )
        return self

    def _should_skip_fuzzy_field(
        self,
        field: FieldConfig,
        restrict_to_author_title_only: bool,
        author_title_names: set[str],
    ) -> bool:
        if "fuzzy" not in (field.query_types or []):
            return True
        return restrict_to_author_title_only and field.name not in author_title_names

    def add_fuzzy_strategy(
        self, fields: list[FieldConfig], operator: str = "and"
    ) -> "DocumentQueryBuilder":
        field_list = []
        restrict = not self._is_short_enough_for_fuzzy_content()
        author_title_names = {
            f.name for f in (self.config.author_fields + self.config.title_fields)
        }

        for field in fields:
            if self._should_skip_fuzzy_field(field, restrict, author_title_names):
                continue
            boosted = self._format_boosted_field_name(
                field.name, self._get_fuzzy_boost(field)
            )
            field_list.append(boosted)

        if field_list:
            self.should_clauses.append(
                Q(
                    "multi_match",
                    query=self.query,
                    fields=field_list,
                    type="best_fields",
                    fuzziness="AUTO",
                    operator=operator,
                )
            )
        return self

    def add_fuzzy_strategy_single_word(
        self, fields: list[FieldConfig]
    ) -> "DocumentQueryBuilder":
        field_list = []
        for field in fields:
            if "fuzzy" not in (field.query_types or []):
                continue
            if field.name in ["paper_title", "title"]:
                boost = self.config.fuzzy_single_word_title_boost
            elif "authors" in field.name:
                boost = self.config.fuzzy_single_word_author_boost
            else:
                boost = field.boost
            field_list.append(self._format_boosted_field_name(field.name, boost))

        if field_list:
            self.should_clauses.append(
                Q(
                    "multi_match",
                    query=self.query,
                    fields=field_list,
                    type="best_fields",
                    fuzziness=self.config.fuzzy_single_word_fuzziness,
                    operator="or",
                )
            )
        return self

    def add_author_name_strategy(self) -> "DocumentQueryBuilder":
        author_fields = [f.get_boosted_name() for f in self.config.author_fields]
        if author_fields:
            self.should_clauses.append(
                Q(
                    "multi_match",
                    query=self.query,
                    type="best_fields",
                    fields=author_fields,
                    operator="or",
                    fuzziness="AUTO",
                    boost=self.config.author_name_strategy_boost,
                )
            )
        return self

    def add_simple_match_strategy(
        self, fields: list[FieldConfig]
    ) -> "DocumentQueryBuilder":
        for field in fields:
            category = self._get_field_category(field)
            base_boost = field.boost * self._get_simple_match_boost(category)

            self.should_clauses.append(
                Q(
                    "match_phrase",
                    **{field.name: {"query": self.query, "boost": base_boost}},
                )
            )
            self.should_clauses.append(
                Q(
                    "match",
                    **{
                        field.name: {
                            "query": self.query,
                            "operator": "and",
                            "boost": base_boost
                            * self.config.simple_match_and_multiplier,
                        }
                    },
                )
            )

            if self._is_short_enough_for_fuzzy_content() and field.name not in [
                "abstract",
                "renderable_text",
            ]:
                self.should_clauses.append(
                    Q(
                        "match",
                        **{
                            field.name: {
                                "query": self.query,
                                "fuzziness": "AUTO",
                                "boost": base_boost
                                * self.config.simple_match_fuzzy_multiplier,
                            }
                        },
                    )
                )
        return self

    def add_cross_field_fallback_strategy(self) -> "DocumentQueryBuilder":
        all_fields = [
            f.get_boosted_name()
            for f in (self.config.author_fields + self.config.title_fields)
        ]
        self.should_clauses.append(
            Q(
                "multi_match",
                query=self.query,
                type="cross_fields",
                operator="or",
                fields=all_fields,
                boost=self.config.fallback_boost,
            )
        )
        return self

    def build(self) -> Q:
        return Q("bool", should=self.should_clauses, minimum_should_match=1)


class PersonQueryBuilder:
    def __init__(self, query: str, config: PersonSearchConfig | None = None):
        self.query = query
        self.config = config or DEFAULT_PERSON_CONFIG

    def build(self) -> Q:
        return Q(
            "multi_match",
            query=self.query,
            fields=self.config.get_fields_with_boosts(),
            type=self.config.query_type,
            fuzziness=self.config.fuzziness,
            operator=self.config.operator,
        )


class UnifiedSearchQueryBuilder:
    def __init__(
        self,
        document_config: DocumentSearchConfig | None = None,
        person_config: PersonSearchConfig | None = None,
    ):
        self.document_config = document_config or DEFAULT_DOCUMENT_CONFIG
        self.person_config = person_config or DEFAULT_PERSON_CONFIG

    def build_document_query(self, query: str) -> Q:
        builder = DocumentQueryBuilder(query, self.document_config)
        is_single_word = DocumentQueryBuilder._is_single_word_query(query)
        cfg = self.document_config

        builder.should_clauses.append(
            Q(
                "multi_match",
                query=query,
                fields=[
                    f"paper_title^{cfg.title_and_match_field_boost}",
                    f"title^{cfg.title_and_match_field_boost}",
                ],
                type="best_fields",
                operator="and",
                boost=cfg.title_and_match_boost,
            )
        )

        builder = (
            builder.add_simple_match_strategy(cfg.title_fields)
            .add_simple_match_strategy(cfg.author_fields)
            .add_author_name_strategy()
            .add_phrase_strategy(cfg.title_fields + cfg.content_fields)
        )

        if not is_single_word:
            builder = builder.add_author_title_combination_strategy()

        prefix_expansions = (
            cfg.prefix_max_expansions_single_word
            if is_single_word
            else cfg.prefix_max_expansions_multi_word
        )
        builder = builder.add_prefix_strategy(
            cfg.title_fields + cfg.author_fields, max_expansions=prefix_expansions
        )

        if is_single_word:
            builder = builder.add_fuzzy_strategy_single_word(
                cfg.title_fields + cfg.author_fields
            )
        else:
            builder = builder.add_fuzzy_strategy(
                cfg.title_fields + cfg.author_fields + cfg.content_fields,
                operator="or",
            )

        return builder.add_cross_field_fallback_strategy().build()

    def build_person_query(self, query: str) -> Q:
        return PersonQueryBuilder(query, self.person_config).build()
