"""Centralized search configuration for unified search."""

import math
from dataclasses import dataclass, field


@dataclass
class FieldConfig:
    name: str
    boost: float = 1.0
    query_types: list[str] | None = None

    def get_boosted_name(self) -> str:
        if math.isclose(self.boost, 1.0):
            return self.name
        return f"{self.name}^{self.boost}"


@dataclass
class FieldBoosts:
    title: float = 3.0
    author_full_name: float = 3.0
    author_last_name: float = 2.5
    author_first_name: float = 2.0
    abstract: float = 1.0
    renderable_text: float = 1.0


@dataclass
class QueryTypeConfig:
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
    field_boosts: FieldBoosts = field(default_factory=FieldBoosts)
    query_types: QueryTypeConfig = field(default_factory=QueryTypeConfig)

    # Query limits
    max_query_words_for_author_title_combo: int = 7
    max_terms_for_fuzzy_content_fields: int = 2

    # DOI
    doi_boost: float = 8.0

    # Title matching
    title_and_match_boost: float = 8.0
    title_and_match_field_boost: float = 7.0

    # Author + Title combination
    author_title_combo_boost: float = 15.0
    cross_field_combo_boost: float = 6.0

    # Simple match
    simple_match_title_boost: float = 1.0
    simple_match_author_boost: float = 0.8
    simple_match_content_boost: float = 1.0
    simple_match_and_multiplier: float = 0.5
    simple_match_fuzzy_multiplier: float = 0.2

    # Phrase
    phrase_title_boost: float = 0.6
    phrase_abstract_boost: float = 0.75
    phrase_content_boost: float = 0.6
    phrase_default_slop: int = 1
    phrase_abstract_slop: int = 2

    # Prefix
    prefix_boost: float = 0.5
    prefix_max_expansions_single_word: int = 10
    prefix_max_expansions_multi_word: int = 20

    # Fuzzy
    fuzzy_title_boost: float = 2.0
    fuzzy_author_boost: float = 2.0
    fuzzy_single_word_title_boost: float = 4.0
    fuzzy_single_word_author_boost: float = 2.0
    fuzzy_single_word_fuzziness: int = 1

    # Author name
    author_name_strategy_boost: float = 2.5

    # Fallback
    fallback_boost: float = 0.2

    # dis_max
    dis_max_tie_breaker: float = 0.1

    @property
    def title_fields(self) -> list[FieldConfig]:
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
        fields = []
        for prefix in ["raw_authors", "authors"]:
            fields.extend([
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
            ])
        return fields

    @property
    def content_fields(self) -> list[FieldConfig]:
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
    full_name_boost: float = 5.0
    first_name_boost: float = 3.0
    last_name_boost: float = 4.0
    headline_boost: float = 2.0
    description_boost: float = 1.0
    fuzziness: str = "AUTO"
    query_type: str = "best_fields"
    operator: str = "or"

    def get_fields_with_boosts(self) -> list[str]:
        return [
            f"full_name^{self.full_name_boost}",
            f"first_name^{self.first_name_boost}",
            f"last_name^{self.last_name_boost}",
            f"headline^{self.headline_boost}",
            f"description^{self.description_boost}",
        ]


DEFAULT_DOCUMENT_CONFIG = DocumentSearchConfig()
DEFAULT_PERSON_CONFIG = PersonSearchConfig()
