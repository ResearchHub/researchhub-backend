"""
Search configuration for unified search.

This module centralizes all tunable parameters for search ranking, including:
- Field definitions and boosts
- Strategy weights and multipliers
- Query behavior settings
- Popularity signal weights

All boost values and thresholds are collected here to enable easy tuning
and A/B testing without modifying query building logic.
"""

import math
from dataclasses import dataclass, field


@dataclass
class FieldConfig:
    """Configuration for a searchable field.

    Attributes:
        name: The OpenSearch field name (e.g., "paper_title", "raw_authors.full_name")
        boost: Base boost multiplier for this field
        query_types: List of query strategies this field supports
            Options: "phrase", "prefix", "fuzzy", "cross_fields"
    """

    name: str
    boost: float = 1.0
    query_types: list[str] | None = None

    def get_boosted_name(self) -> str:
        """Return field name with boost suffix for OpenSearch."""
        if math.isclose(self.boost, 1.0):
            return self.name
        return f"{self.name}^{self.boost}"


@dataclass
class PopularityConfig:
    """Configuration for popularity signal boosts in search ranking.

    These signals are combined using OpenSearch's function_score query to
    influence ranking based on document engagement and authority metrics.

    Attributes:
        enabled: Whether to apply popularity boosting at all.
        citations_weight: Weight for citation count (papers only). Higher values
            favor highly-cited papers. Uses log1p normalization.
        discussion_weight: Weight for discussion/comment count. Higher values
            favor documents with more community engagement.
        hot_score_weight: Weight for hot_score (time-decayed popularity).
            Already a composite signal including bounties, tips, reviews.
        score_weight: Weight for vote-based quality score.
        boost_mode: How to combine function score with query score.
            Options: "multiply", "sum", "avg", "replace", "max", "min".
        score_mode: How to combine multiple function scores.
            Options: "sum", "multiply", "avg", "first", "max", "min".
    """

    enabled: bool = True
    citations_weight: float = 1.5
    discussion_weight: float = 1.2
    hot_score_weight: float = 1.0
    score_weight: float = 0.8
    boost_mode: str = "multiply"
    score_mode: str = "sum"


@dataclass
class FieldBoosts:
    """Base boost values for different field types.

    These boosts represent the relative importance of each field type
    when matching search queries. Higher values = more influence on ranking.

    The boosts are applied as multipliers in OpenSearch queries.
    """

    # -------------------------------------------------------------------------
    # Title Field Boosts
    # -------------------------------------------------------------------------
    # Title is the most important field - exact title matches should rank highest
    title: float = 3.0

    # -------------------------------------------------------------------------
    # Author Name Field Boosts
    # -------------------------------------------------------------------------
    # Full name is most valuable (exact match on "John Smith")
    author_full_name: float = 3.0
    # Last name slightly less (common search pattern: "Smith cancer research")
    author_last_name: float = 2.5
    # First name least valuable (too ambiguous alone)
    author_first_name: float = 2.0

    # -------------------------------------------------------------------------
    # Content Field Boosts
    # -------------------------------------------------------------------------
    # Abstract is a summary - matches here are meaningful
    abstract: float = 1.0
    # Full text has more noise - lower boost to prevent false positives
    renderable_text: float = 1.0


@dataclass
class QueryTypeConfig:
    """Maps field categories to their supported query types.

    Query types determine which search strategies can use each field:
    - "phrase": Exact phrase matching with word order
    - "prefix": Autocomplete-style prefix matching
    - "fuzzy": Typo-tolerant matching
    - "cross_fields": Multi-field term matching
    """

    title_query_types: list[str] = field(
        default_factory=lambda: ["phrase", "prefix", "fuzzy"]
    )
    author_query_types: list[str] = field(
        default_factory=lambda: ["cross_fields", "fuzzy", "prefix"]
    )
    abstract_query_types: list[str] = field(default_factory=lambda: ["phrase", "fuzzy"])
    content_query_types: list[str] = field(default_factory=lambda: ["fuzzy"])


@dataclass
class DocumentSearchConfig:
    """Configuration for document (paper/post) search.

    Centralizes all tunable parameters for document search ranking.
    """

    # ==========================================================================
    # Field Boost Configuration
    # ==========================================================================

    field_boosts: FieldBoosts = field(default_factory=FieldBoosts)
    query_types: QueryTypeConfig = field(default_factory=QueryTypeConfig)

    # ==========================================================================
    # Query Limits
    # ==========================================================================

    # Maximum words to use for author+title combination queries.
    # Prevents query explosion with very long queries.
    max_query_words_for_author_title_combo: int = 7

    # Maximum query terms before disabling fuzzy matching on content fields.
    # Fuzzy on long queries produces too much noise.
    max_terms_for_fuzzy_content_fields: int = 2

    # ==========================================================================
    # DOI Matching
    # ==========================================================================

    doi_boost: float = 8.0

    # ==========================================================================
    # Title Matching
    # ==========================================================================

    # Boost for exact title AND match (all query terms must appear in title)
    title_and_match_boost: float = 8.0
    title_and_match_field_boost: float = 7.0  # Applied to paper_title and title

    # ==========================================================================
    # Author + Title Combination Strategy
    # ==========================================================================

    # Boost when both author AND title match (highest priority)
    author_title_combo_boost: float = 12.0

    # Boost for cross-field matching across author and title
    cross_field_combo_boost: float = 6.0

    # ==========================================================================
    # Simple Match Strategy Multipliers
    # ==========================================================================

    # Category-specific boosts for simple match
    simple_match_title_boost: float = 1.0
    simple_match_author_boost: float = 0.8
    simple_match_content_boost: float = 1.0

    # Sub-strategy multipliers (applied on top of category boost)
    simple_match_and_multiplier: float = 0.5  # AND operator match
    simple_match_fuzzy_multiplier: float = 0.2  # Fuzzy match for typos

    # ==========================================================================
    # Phrase Strategy
    # ==========================================================================

    phrase_title_boost: float = 0.6
    phrase_abstract_boost: float = 0.75
    phrase_content_boost: float = 0.6

    # Slop values (word position flexibility)
    phrase_default_slop: int = 1
    phrase_abstract_slop: int = 2

    # ==========================================================================
    # Prefix Strategy (autocomplete-style)
    # ==========================================================================

    prefix_boost: float = 0.5

    # Max term expansions for prefix matching
    prefix_max_expansions_single_word: int = 10
    prefix_max_expansions_multi_word: int = 20

    # ==========================================================================
    # Fuzzy Strategy (typo tolerance)
    # ==========================================================================

    fuzzy_title_boost: float = 2.0
    fuzzy_author_boost: float = 2.0

    # Single-word query fuzzy boosts (stricter)
    fuzzy_single_word_title_boost: float = 4.0
    fuzzy_single_word_author_boost: float = 2.0
    fuzzy_single_word_fuzziness: int = 1  # Edit distance (stricter than AUTO)

    # ==========================================================================
    # Author Name Strategy
    # ==========================================================================

    author_name_strategy_boost: float = 2.5

    # ==========================================================================
    # Fallback Strategy
    # ==========================================================================

    # Low boost for cross-field OR fallback (ensures some results)
    fallback_boost: float = 0.2

    # ==========================================================================
    # dis_max Query Settings
    # ==========================================================================

    # Tie breaker for dis_max queries (rewards matching multiple fields)
    dis_max_tie_breaker: float = 0.1

    # ==========================================================================
    # Computed Field Definitions
    # ==========================================================================

    @property
    def title_fields(self) -> list[FieldConfig]:
        """Generate title field configs from boost settings."""
        return [
            FieldConfig(
                "paper_title",
                boost=self.field_boosts.title,
                query_types=self.query_types.title_query_types,
            ),
            FieldConfig(
                "title",
                boost=self.field_boosts.title,
                query_types=self.query_types.title_query_types,
            ),
        ]

    @property
    def author_fields(self) -> list[FieldConfig]:
        """Generate author field configs from boost settings.

        Creates entries for both raw_authors (papers) and authors (posts)
        with consistent boosts for full_name, last_name, and first_name.
        """
        author_prefixes = ["raw_authors", "authors"]
        fields = []

        for prefix in author_prefixes:
            fields.extend(
                [
                    FieldConfig(
                        f"{prefix}.full_name",
                        boost=self.field_boosts.author_full_name,
                        query_types=self.query_types.author_query_types,
                    ),
                    FieldConfig(
                        f"{prefix}.last_name",
                        boost=self.field_boosts.author_last_name,
                        query_types=self.query_types.author_query_types,
                    ),
                    FieldConfig(
                        f"{prefix}.first_name",
                        boost=self.field_boosts.author_first_name,
                        query_types=self.query_types.author_query_types,
                    ),
                ]
            )

        return fields

    @property
    def content_fields(self) -> list[FieldConfig]:
        """Generate content field configs from boost settings."""
        return [
            FieldConfig(
                "abstract",
                boost=self.field_boosts.abstract,
                query_types=self.query_types.abstract_query_types,
            ),
            FieldConfig(
                "renderable_text",
                boost=self.field_boosts.renderable_text,
                query_types=self.query_types.content_query_types,
            ),
        ]


@dataclass
class PersonSearchConfig:
    """Configuration for person/author search."""

    # Field boosts for person search
    full_name_boost: float = 5.0
    first_name_boost: float = 3.0
    last_name_boost: float = 4.0
    headline_boost: float = 2.0
    description_boost: float = 1.0

    # Query settings
    fuzziness: str = "AUTO"
    query_type: str = "best_fields"
    operator: str = "or"

    def get_fields_with_boosts(self) -> list[str]:
        """Return list of fields with boost suffixes."""
        return [
            f"full_name^{self.full_name_boost}",
            f"first_name^{self.first_name_boost}",
            f"last_name^{self.last_name_boost}",
            f"headline^{self.headline_boost}",
            f"description^{self.description_boost}",
        ]


# =============================================================================
# Default Configuration Instances
# =============================================================================

DEFAULT_DOCUMENT_CONFIG = DocumentSearchConfig()
DEFAULT_PERSON_CONFIG = PersonSearchConfig()
DEFAULT_POPULARITY_CONFIG = PopularityConfig()
