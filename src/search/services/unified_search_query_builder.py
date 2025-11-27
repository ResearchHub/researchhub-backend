import math
from dataclasses import dataclass

from opensearchpy import Q

from utils.doi import DOI


@dataclass
class FieldConfig:

    name: str
    boost: float = 1.0
    query_types: list[str] | None = None

    def get_boosted_name(self) -> str:
        """Return field name with boost suffix."""
        if math.isclose(self.boost, 1.0):
            return self.name
        return f"{self.name}^{self.boost}"


class DocumentQueryBuilder:

    MAX_QUERY_WORDS_FOR_AUTHOR_TITLE_COMBO = 7
    # If its more than 3 terms disable fuzzy content fields
    MAX_TERMS_FOR_FUZZY_CONTENT_FIELDS = 3

    # Maps (strategy_type, field_category) -> boost value
    STRATEGY_BOOSTS = {
        # Simple match strategy boosts
        ("simple_match", "title"): 1.0,
        ("simple_match", "author"): 0.8,
        ("simple_match", "content"): 1.0,
        # Simple match sub-strategy multipliers
        ("simple_match_and", "all"): 0.7,
        ("simple_match_fuzzy", "all"): 0.3,
        # Phrase strategy boosts
        ("phrase", "title"): 0.6,
        ("phrase", "abstract"): 0.75,
        ("phrase", "content"): 0.6,
        # Prefix strategy boosts
        ("prefix", "all"): 0.5,
        # Fuzzy strategy boosts (absolute values, not multipliers)
        ("fuzzy", "title"): 4.0,
        ("fuzzy", "author"): 2.0,
        ("fuzzy", "content"): None,
    }

    # Field configurations
    TITLE_FIELDS = [
        FieldConfig(
            "paper_title", boost=5.0, query_types=["phrase", "prefix", "fuzzy"]
        ),
        FieldConfig("title", boost=5.0, query_types=["phrase", "prefix", "fuzzy"]),
    ]

    AUTHOR_FIELDS = [
        FieldConfig(
            "raw_authors.full_name",
            boost=3.0,
            query_types=["cross_fields", "fuzzy", "prefix"],
        ),
        FieldConfig(
            "raw_authors.last_name",
            boost=2.5,
            query_types=["cross_fields", "fuzzy", "prefix"],
        ),
        FieldConfig(
            "raw_authors.first_name",
            boost=2.0,
            query_types=["cross_fields", "fuzzy", "prefix"],
        ),
        FieldConfig(
            "authors.full_name",
            boost=3.0,
            query_types=["cross_fields", "fuzzy", "prefix"],
        ),
        FieldConfig(
            "authors.last_name",
            boost=2.5,
            query_types=["cross_fields", "fuzzy", "prefix"],
        ),
        FieldConfig(
            "authors.first_name",
            boost=2.0,
            query_types=["cross_fields", "fuzzy", "prefix"],
        ),
    ]

    CONTENT_FIELDS = [
        FieldConfig("abstract", boost=2.0, query_types=["phrase", "fuzzy"]),
        FieldConfig("renderable_text", boost=1.0, query_types=["fuzzy"]),
    ]

    def __init__(self, query: str):
        """Initialize builder with search query."""
        self.query = query
        # Pre-split query terms for reuse in fuzzy-gating heuristics
        self._query_terms: list[str] = [w for w in (query or "").split() if w]
        self.should_clauses: list[Q] = []
        self._add_doi_match_if_applicable()

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

    def _get_query_term_count(self) -> int:
        return len(self._query_terms)

    def _is_short_enough_for_fuzzy_content(self) -> bool:
        return self._get_query_term_count() <= self.MAX_TERMS_FOR_FUZZY_CONTENT_FIELDS

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

    # Add strategy that allows author and title to co-occur.
    def add_author_title_combination_strategy(self) -> "DocumentQueryBuilder":
        # Truncate query to prevent query explosion with long queries
        truncated_query = self._limit_query_to_max_words(
            self.query, self.MAX_QUERY_WORDS_FOR_AUTHOR_TITLE_COMBO
        )

        author_fields = []
        title_fields = []
        for field in self.AUTHOR_FIELDS:
            author_fields.append(field.get_boosted_name())
        for field in self.TITLE_FIELDS:
            title_fields.append(field.get_boosted_name())

        # Strategy 1: Bool query that requires author match AND title match
        # HIGHEST PRIORITY - should rank first when both author and title match
        author_queries = []
        for field in self.AUTHOR_FIELDS:
            author_queries.append(
                Q(
                    "match",
                    **{
                        field.name: {
                            "query": truncated_query,
                            "operator": "or",
                        }
                    },
                )
            )

        title_queries = []
        for field in self.TITLE_FIELDS:
            title_queries.append(
                Q(
                    "match",
                    **{
                        field.name: {
                            "query": truncated_query,
                            "operator": "or",
                        }
                    },
                )
            )

        # Combine: (author match) AND (title match)
        # Very high boost to ensure author+title matches rank first
        if author_queries and title_queries:
            author_match = Q("bool", should=author_queries, minimum_should_match=1)
            title_match = Q("bool", should=title_queries, minimum_should_match=1)
            # Boost of 15.0 ensures author+title combos rank above title-only matches
            author_title_combo = Q("bool", must=[author_match, title_match], boost=15.0)
            self.should_clauses.append(author_title_combo)

        # Strategy 2: Cross-field matching - allows terms to match across fields
        # Lower boost than author+title combo, but still useful for flexible matching
        all_fields = author_fields + title_fields
        combo_query = Q(
            "multi_match",
            query=self.query,
            type="cross_fields",
            operator="or",
            fields=all_fields,
            boost=6.0,
        )
        self.should_clauses.append(combo_query)

        return self

    def add_phrase_strategy(
        self, fields: list[FieldConfig], slop: int = 1
    ) -> "DocumentQueryBuilder":

        queries = []
        for field in fields:
            if "phrase" in (field.query_types or []):
                # Abstract gets slop=2, titles get slop=1
                field_slop = 2 if field.name == "abstract" else slop
                # Get boost from config
                if field.name == "abstract":
                    strategy_boost = self.STRATEGY_BOOSTS[("phrase", "abstract")]
                else:
                    category = self._get_field_category(field)
                    strategy_boost = self.STRATEGY_BOOSTS[("phrase", category)]
                field_boost = field.boost * strategy_boost
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
    ) -> "DocumentQueryBuilder":
        """Add phrase prefix strategy for specified fields."""
        queries = []
        prefix_boost = self.STRATEGY_BOOSTS[("prefix", "all")]
        for field in fields:
            if "prefix" in (field.query_types or []):
                queries.append(
                    Q(
                        "match_phrase_prefix",
                        **{
                            field.name: {
                                "query": self.query,
                                "max_expansions": max_expansions,
                                "boost": field.boost * prefix_boost,
                            }
                        },
                    )
                )

        if queries:
            prefix_query = Q("dis_max", queries=queries, tie_breaker=0.1)
            self.should_clauses.append(prefix_query)
        return self

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

    def _get_fuzzy_boost(self, field: FieldConfig) -> float:
        """Get fuzzy boost for a field from strategy config."""
        if field.name in ["paper_title", "title"]:
            return self.STRATEGY_BOOSTS[("fuzzy", "title")]
        if "authors" in field.name:
            return self.STRATEGY_BOOSTS[("fuzzy", "author")]
        # For content fields, use base boost (config has None as fallback)
        return field.boost

    def _format_boosted_field_name(self, field_name: str, boost: float) -> str:
        """Format field name with boost suffix."""
        if math.isclose(boost, 1.0):
            return field_name
        if math.isclose(boost, round(boost)):
            return f"{field_name}^{int(round(boost))}"
        return f"{field_name}^{boost}"

    def add_fuzzy_strategy(
        self,
        fields: list[FieldConfig],
        operator: str = "and",
    ) -> "DocumentQueryBuilder":
        """Add fuzzy match strategy for specified fields."""
        field_list = []
        restrict_to_author_title_only = not self._is_short_enough_for_fuzzy_content()
        author_title_names = {f.name for f in (self.AUTHOR_FIELDS + self.TITLE_FIELDS)}

        for field in fields:
            if self._should_skip_fuzzy_field(
                field, restrict_to_author_title_only, author_title_names
            ):
                continue

            fuzzy_boost = self._get_fuzzy_boost(field)
            boosted_name = self._format_boosted_field_name(field.name, fuzzy_boost)
            field_list.append(boosted_name)

        if field_list:
            # Use best_fields instead of cross_fields - fuzziness not allowed
            # with cross_fields type
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
            if "fuzzy" in (field.query_types or []):
                # Fuzzy strategy uses different boosts:
                # - Titles: 4.0 (from 5.0 base)
                # - Authors: 2.0 (from 3.0 base)
                if field.name in ["paper_title", "title"]:
                    fuzzy_boost = 4.0
                elif "authors" in field.name:
                    fuzzy_boost = 2.0
                else:
                    fuzzy_boost = field.boost

                boosted_name = self._format_boosted_field_name(field.name, fuzzy_boost)
                field_list.append(boosted_name)

        if field_list:
            # Use stricter fuzziness (1 edit distance) instead of AUTO for single words
            fuzzy_query = Q(
                "multi_match",
                query=self.query,
                fields=field_list,
                type="best_fields",
                fuzziness=1,  # Stricter than AUTO for single words
                operator="or",
            )
            self.should_clauses.append(fuzzy_query)
        return self

    def add_author_name_strategy(self) -> "DocumentQueryBuilder":
        author_fields = []
        for field in self.AUTHOR_FIELDS:
            author_fields.append(field.get_boosted_name())

        if author_fields:
            author_query = Q(
                "multi_match",
                query=self.query,
                type="best_fields",
                fields=author_fields,
                operator="or",
                fuzziness="AUTO",
                boost=2.5,  # Boost author-specific queries
            )
            self.should_clauses.append(author_query)
        return self

    def _get_field_category(self, field: FieldConfig) -> str:
        """Determine field category for boost lookup."""
        if field.name in ["paper_title", "title"]:
            return "title"
        if "authors" in field.name:
            return "author"
        return "content"

    def add_simple_match_strategy(
        self, fields: list[FieldConfig]
    ) -> "DocumentQueryBuilder":
        for field in fields:
            category = self._get_field_category(field)
            strategy_boost = self.STRATEGY_BOOSTS[("simple_match", category)]
            base_boost = field.boost * strategy_boost

            # Strategy 1: Phrase match (highest relevance)
            self.should_clauses.append(
                Q(
                    "match_phrase",
                    **{
                        field.name: {
                            "query": self.query,
                            "boost": base_boost,
                        }
                    },
                )
            )
            # Strategy 2: Match with AND operator - all words must be in field
            and_multiplier = self.STRATEGY_BOOSTS[("simple_match_and", "all")]
            self.should_clauses.append(
                Q(
                    "match",
                    **{
                        field.name: {
                            "query": self.query,
                            "operator": "and",
                            "boost": base_boost * and_multiplier,
                        }
                    },
                )
            )
            # Strategy 3: Fuzzy match for typos (gated)
            # Only apply fuzzy matching for short queries and exclude content fields
            if self._is_short_enough_for_fuzzy_content() and field.name not in [
                "abstract",
                "renderable_text",
            ]:
                fuzzy_multiplier = self.STRATEGY_BOOSTS[("simple_match_fuzzy", "all")]
                self.should_clauses.append(
                    Q(
                        "match",
                        **{
                            field.name: {
                                "query": self.query,
                                "fuzziness": "AUTO",
                                "boost": base_boost * fuzzy_multiplier,
                            }
                        },
                    )
                )
        return self

    def add_cross_field_fallback_strategy(self) -> "DocumentQueryBuilder":
        """Add cross-field OR fallback strategy for partial matches.

        This ensures results even when strict AND matching fails.
        Uses OR operator to allow partial matches across fields.
        """
        # Combine all fields for broad coverage
        all_fields = []
        for field in self.AUTHOR_FIELDS + self.TITLE_FIELDS + self.CONTENT_FIELDS:
            all_fields.append(field.get_boosted_name())

        fallback_query = Q(
            "multi_match",
            query=self.query,
            type="cross_fields",
            operator="or",
            fields=all_fields,
            boost=0.8,
        )
        self.should_clauses.append(fallback_query)
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
        """Build document query with complexity limits for single-word queries."""
        builder = DocumentQueryBuilder(query)
        is_single_word = DocumentQueryBuilder._is_single_word_query(query)

        title_fields = DocumentQueryBuilder.TITLE_FIELDS
        author_fields = DocumentQueryBuilder.AUTHOR_FIELDS
        content_fields = DocumentQueryBuilder.CONTENT_FIELDS

        builder = (
            builder.add_simple_match_strategy(title_fields)
            .add_simple_match_strategy(author_fields)
            .add_author_name_strategy()
            .add_phrase_strategy(title_fields + content_fields, slop=1)
        )

        if not is_single_word:
            builder = builder.add_author_title_combination_strategy()

        # max_expansions limits unique terms OpenSearch collects from the index
        # that match the prefix of the LAST word. Prevents query explosion.
        #
        # Examples:
        # - Query: "systematic"
        #   - Matches: "systematic review", "systematic analysis", etc.
        #   - max_expansions=10: collects up to 10 unique terms following
        #     "systematic" (e.g., "review", "analysis", "design"...)
        #
        # - Query: "systematic design"
        #   - Matches: "systematic design patterns", etc.
        #   - max_expansions=20: collects up to 20 unique terms following
        #     "design" (e.g., "patterns", "methodology"...)
        #
        # Lower (10) for single-word reduces overhead.
        # Higher (20) for multi-word improves recall.
        prefix_expansions = 10 if is_single_word else 20
        builder = builder.add_prefix_strategy(
            title_fields + author_fields,
            max_expansions=prefix_expansions,
        )

        if is_single_word:
            builder = builder.add_fuzzy_strategy_single_word(
                title_fields + author_fields
            )
        else:
            builder = builder.add_fuzzy_strategy(
                title_fields + author_fields + content_fields,
                operator="or",
            )

        builder = builder.add_cross_field_fallback_strategy()

        return builder.build()

    def build_person_query(self, query: str) -> Q:

        builder = PersonQueryBuilder(query)
        return builder.build()
