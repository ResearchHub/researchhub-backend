"""
Query builders for unified search.

This module contains the query building logic for document and person search.
All configuration values are imported from search_config.py.
"""

import math

from opensearchpy import Q

from search.services.search_config import (
    DEFAULT_DOCUMENT_CONFIG,
    DEFAULT_PERSON_CONFIG,
    DEFAULT_POPULARITY_CONFIG,
    DocumentSearchConfig,
    FieldConfig,
    PersonSearchConfig,
    PopularityConfig,
)
from utils.doi import DOI


class DocumentQueryBuilder:
    """Builds OpenSearch queries for document (paper/post) search.

    Uses a fluent interface pattern where strategies can be chained:
        builder.add_phrase_strategy(...).add_fuzzy_strategy(...).build()

    All configuration values come from DocumentSearchConfig.
    """

    def __init__(self, query: str, config: DocumentSearchConfig | None = None):
        """Initialize builder with search query and optional config.

        Args:
            query: The user's search query string.
            config: Search configuration. Uses DEFAULT_DOCUMENT_CONFIG if None.
        """
        self.query = query
        self.config = config or DEFAULT_DOCUMENT_CONFIG
        self._query_terms: list[str] = [w for w in (query or "").split() if w]
        self.should_clauses: list[Q] = []
        self._add_doi_match_if_applicable()

    # =========================================================================
    # Static/Utility Methods
    # =========================================================================

    @staticmethod
    def _is_single_word_query(query: str) -> bool:
        words = query.strip().split()
        return len(words) == 1

    @staticmethod
    def _limit_query_to_max_words(query: str, max_words: int) -> str:
        words = query.split()
        if len(words) <= max_words:
            return query
        return " ".join(words[:max_words])

    def _format_boosted_field_name(self, field_name: str, boost: float) -> str:
        """Format field name with boost suffix."""
        if math.isclose(boost, 1.0):
            return field_name
        if math.isclose(boost, round(boost)):
            return f"{field_name}^{int(round(boost))}"
        return f"{field_name}^{boost}"

    def _get_query_term_count(self) -> int:
        return len(self._query_terms)

    def _is_short_enough_for_fuzzy_content(self) -> bool:
        return (
            self._get_query_term_count()
            <= self.config.max_terms_for_fuzzy_content_fields
        )

    def _get_field_category(self, field: FieldConfig) -> str:
        """Determine field category for boost lookup."""
        if field.name in ["paper_title", "title"]:
            return "title"
        if "authors" in field.name:
            return "author"
        return "content"

    def _get_simple_match_boost(self, category: str) -> float:
        """Get simple match boost for a field category."""
        if category == "title":
            return self.config.simple_match_title_boost
        if category == "author":
            return self.config.simple_match_author_boost
        return self.config.simple_match_content_boost

    def _get_phrase_boost(self, field: FieldConfig) -> float:
        """Get phrase strategy boost for a field."""
        if field.name == "abstract":
            return self.config.phrase_abstract_boost
        category = self._get_field_category(field)
        if category == "title":
            return self.config.phrase_title_boost
        return self.config.phrase_content_boost

    def _get_fuzzy_boost(self, field: FieldConfig) -> float:
        """Get fuzzy boost for a field."""
        if field.name in ["paper_title", "title"]:
            return self.config.fuzzy_title_boost
        if "authors" in field.name:
            return self.config.fuzzy_author_boost
        return field.boost

    # =========================================================================
    # DOI Matching
    # =========================================================================

    def _add_doi_match_if_applicable(self):
        """Add DOI exact match if query is a DOI."""
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

    # =========================================================================
    # Strategy: Author + Title Combination
    # =========================================================================

    def add_author_title_combination_strategy(self) -> "DocumentQueryBuilder":
        """Add strategy for queries containing both author and title terms."""
        truncated_query = self._limit_query_to_max_words(
            self.query, self.config.max_query_words_for_author_title_combo
        )

        author_fields = [f.get_boosted_name() for f in self.config.author_fields]
        title_fields = [f.get_boosted_name() for f in self.config.title_fields]

        # Strategy 1: Bool query requiring author AND title match
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
            author_title_combo = Q(
                "bool",
                must=[author_match, title_match],
                boost=self.config.author_title_combo_boost,
            )
            self.should_clauses.append(author_title_combo)

        # Strategy 2: Cross-field matching
        all_fields = author_fields + title_fields
        combo_query = Q(
            "multi_match",
            query=self.query,
            type="cross_fields",
            operator="or",
            fields=all_fields,
            boost=self.config.cross_field_combo_boost,
        )
        self.should_clauses.append(combo_query)

        return self

    # =========================================================================
    # Strategy: Phrase Match
    # =========================================================================

    def add_phrase_strategy(
        self, fields: list[FieldConfig], slop: int | None = None
    ) -> "DocumentQueryBuilder":
        """Add phrase matching strategy for specified fields."""
        if slop is None:
            slop = self.config.phrase_default_slop

        queries = []
        for field in fields:
            if "phrase" not in (field.query_types or []):
                continue

            field_slop = (
                self.config.phrase_abstract_slop if field.name == "abstract" else slop
            )
            phrase_boost = self._get_phrase_boost(field)
            field_boost = field.boost * phrase_boost

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
            phrase_query = Q(
                "dis_max", queries=queries, tie_breaker=self.config.dis_max_tie_breaker
            )
            self.should_clauses.append(phrase_query)
        return self

    # =========================================================================
    # Strategy: Prefix Match (Autocomplete)
    # =========================================================================

    def add_prefix_strategy(
        self,
        fields: list[FieldConfig],
        max_expansions: int | None = None,
    ) -> "DocumentQueryBuilder":
        """Add phrase prefix strategy for autocomplete-style matching."""
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
            prefix_query = Q(
                "dis_max", queries=queries, tie_breaker=self.config.dis_max_tie_breaker
            )
            self.should_clauses.append(prefix_query)
        return self

    # =========================================================================
    # Strategy: Fuzzy Match (Typo Tolerance)
    # =========================================================================

    def _should_skip_fuzzy_field(
        self,
        field: FieldConfig,
        restrict_to_author_title_only: bool,
        author_title_names: set[str],
    ) -> bool:
        """Check if fuzzy field should be skipped for longer queries."""
        if "fuzzy" not in (field.query_types or []):
            return True
        return restrict_to_author_title_only and field.name not in author_title_names

    def add_fuzzy_strategy(
        self,
        fields: list[FieldConfig],
        operator: str = "and",
    ) -> "DocumentQueryBuilder":
        """Add fuzzy match strategy for typo tolerance."""
        field_list = []
        restrict_to_author_title_only = not self._is_short_enough_for_fuzzy_content()
        author_title_names = {
            f.name for f in (self.config.author_fields + self.config.title_fields)
        }

        for field in fields:
            if self._should_skip_fuzzy_field(
                field, restrict_to_author_title_only, author_title_names
            ):
                continue

            fuzzy_boost = self._get_fuzzy_boost(field)
            boosted_name = self._format_boosted_field_name(field.name, fuzzy_boost)
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

    def add_fuzzy_strategy_single_word(
        self,
        fields: list[FieldConfig],
    ) -> "DocumentQueryBuilder":
        """Add fuzzy match strategy with stricter fuzziness for single-word queries."""
        field_list = []
        for field in fields:
            if "fuzzy" not in (field.query_types or []):
                continue

            if field.name in ["paper_title", "title"]:
                fuzzy_boost = self.config.fuzzy_single_word_title_boost
            elif "authors" in field.name:
                fuzzy_boost = self.config.fuzzy_single_word_author_boost
            else:
                fuzzy_boost = field.boost

            boosted_name = self._format_boosted_field_name(field.name, fuzzy_boost)
            field_list.append(boosted_name)

        if field_list:
            fuzzy_query = Q(
                "multi_match",
                query=self.query,
                fields=field_list,
                type="best_fields",
                fuzziness=self.config.fuzzy_single_word_fuzziness,
                operator="or",
            )
            self.should_clauses.append(fuzzy_query)
        return self

    # =========================================================================
    # Strategy: Author Name
    # =========================================================================

    def add_author_name_strategy(self) -> "DocumentQueryBuilder":
        """Add author-specific matching strategy."""
        author_fields = [f.get_boosted_name() for f in self.config.author_fields]

        if author_fields:
            author_query = Q(
                "multi_match",
                query=self.query,
                type="best_fields",
                fields=author_fields,
                operator="or",
                fuzziness="AUTO",
                boost=self.config.author_name_strategy_boost,
            )
            self.should_clauses.append(author_query)
        return self

    # =========================================================================
    # Strategy: Simple Match
    # =========================================================================

    def add_simple_match_strategy(
        self, fields: list[FieldConfig]
    ) -> "DocumentQueryBuilder":
        """Add simple match strategies (phrase, AND, fuzzy) for fields."""
        for field in fields:
            category = self._get_field_category(field)
            strategy_boost = self._get_simple_match_boost(category)
            base_boost = field.boost * strategy_boost

            # Sub-strategy 1: Phrase match (highest relevance)
            self.should_clauses.append(
                Q(
                    "match_phrase",
                    **{field.name: {"query": self.query, "boost": base_boost}},
                )
            )

            # Sub-strategy 2: AND operator match
            and_boost = base_boost * self.config.simple_match_and_multiplier
            self.should_clauses.append(
                Q(
                    "match",
                    **{
                        field.name: {
                            "query": self.query,
                            "operator": "and",
                            "boost": and_boost,
                        }
                    },
                )
            )

            # Sub-strategy 3: Fuzzy match (gated for short queries, non-content)
            if self._is_short_enough_for_fuzzy_content() and field.name not in [
                "abstract",
                "renderable_text",
            ]:
                fuzzy_boost = base_boost * self.config.simple_match_fuzzy_multiplier
                self.should_clauses.append(
                    Q(
                        "match",
                        **{
                            field.name: {
                                "query": self.query,
                                "fuzziness": "AUTO",
                                "boost": fuzzy_boost,
                            }
                        },
                    )
                )
        return self

    # =========================================================================
    # Strategy: Cross-Field Fallback
    # =========================================================================

    def add_cross_field_fallback_strategy(self) -> "DocumentQueryBuilder":
        """Add cross-field OR fallback strategy for partial matches.

        Ensures results even when strict AND matching fails.
        """
        all_fields = [
            f.get_boosted_name()
            for f in (self.config.author_fields + self.config.title_fields)
        ]

        fallback_query = Q(
            "multi_match",
            query=self.query,
            type="cross_fields",
            operator="or",
            fields=all_fields,
            boost=self.config.fallback_boost,
        )
        self.should_clauses.append(fallback_query)
        return self

    # =========================================================================
    # Build Methods
    # =========================================================================

    def build(self) -> Q:
        """Build the final bool query from accumulated should clauses."""
        return Q("bool", should=self.should_clauses, minimum_should_match=1)

    def build_with_popularity_boost(self, popularity_config: PopularityConfig) -> Q:
        """Build query with popularity signal boosting using function_score.

        Wraps the text relevance query in a function_score query that combines
        text matching with popularity signals (citations, discussion_count,
        hot_score, score).
        """
        text_query = self.build()

        if not popularity_config.enabled:
            return text_query

        functions = []

        if popularity_config.citations_weight > 0:
            functions.append(
                {
                    "field_value_factor": {
                        "field": "citations",
                        "factor": popularity_config.citations_weight,
                        "modifier": "log1p",
                        "missing": 1,
                    }
                }
            )

        if popularity_config.discussion_weight > 0:
            functions.append(
                {
                    "field_value_factor": {
                        "field": "discussion_count",
                        "factor": popularity_config.discussion_weight,
                        "modifier": "log1p",
                        "missing": 1,
                    }
                }
            )

        if popularity_config.hot_score_weight > 0:
            functions.append(
                {
                    "field_value_factor": {
                        "field": "hot_score",
                        "factor": popularity_config.hot_score_weight,
                        "modifier": "log1p",
                        "missing": 1,
                    }
                }
            )

        if popularity_config.score_weight > 0:
            functions.append(
                {
                    "field_value_factor": {
                        "field": "score",
                        "factor": popularity_config.score_weight,
                        "modifier": "log1p",
                        "missing": 1,
                    }
                }
            )

        if not functions:
            return text_query

        return Q(
            "function_score",
            query=text_query,
            functions=functions,
            score_mode=popularity_config.score_mode,
            boost_mode=popularity_config.boost_mode,
        )


class PersonQueryBuilder:
    """Builds OpenSearch queries for person/author search."""

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
    """High-level query builder that orchestrates document and person search."""

    def __init__(
        self,
        document_config: DocumentSearchConfig | None = None,
        person_config: PersonSearchConfig | None = None,
        popularity_config: PopularityConfig | None = None,
    ):
        self.document_config = document_config or DEFAULT_DOCUMENT_CONFIG
        self.person_config = person_config or DEFAULT_PERSON_CONFIG
        self.popularity_config = popularity_config or DEFAULT_POPULARITY_CONFIG

    def _build_document_query_builder(self, query: str) -> DocumentQueryBuilder:
        """Build and configure DocumentQueryBuilder with all strategies."""
        builder = DocumentQueryBuilder(query, self.document_config)
        is_single_word = DocumentQueryBuilder._is_single_word_query(query)
        cfg = self.document_config

        # Strong title AND match
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
            cfg.title_fields + cfg.author_fields,
            max_expansions=prefix_expansions,
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

        builder = builder.add_cross_field_fallback_strategy()

        return builder

    def build_document_query(self, query: str) -> Q:
        """Build document query without popularity boosting."""
        builder = self._build_document_query_builder(query)
        return builder.build()

    def build_document_query_with_popularity(
        self, query: str, popularity_config: PopularityConfig | None = None
    ) -> Q:
        """Build document query with popularity signal boosting."""
        if popularity_config is None:
            popularity_config = self.popularity_config

        builder = self._build_document_query_builder(query)
        return builder.build_with_popularity_boost(popularity_config)

    def build_person_query(self, query: str) -> Q:
        """Build person/author search query."""
        builder = PersonQueryBuilder(query, self.person_config)
        return builder.build()


# Re-export config classes for convenience
__all__ = [
    "DocumentQueryBuilder",
    "DocumentSearchConfig",
    "FieldConfig",
    "PersonQueryBuilder",
    "PersonSearchConfig",
    "PopularityConfig",
    "UnifiedSearchQueryBuilder",
]
