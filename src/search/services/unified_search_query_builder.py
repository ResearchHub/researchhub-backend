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
        if math.isclose(self.boost, 1.0):
            return self.name
        return f"{self.name}^{self.boost}"


@dataclass
class PopularityConfig:
    """Configuration for popularity boosting using hot_score_v2."""

    enabled: bool = True
    weight: float = 1.0
    boost_mode: str = "sum"


DEFAULT_POPULARITY_CONFIG = PopularityConfig()


class DocumentQueryBuilder:
    MAX_QUERY_WORDS_FOR_AUTHOR_TITLE_COMBO = 7
    MAX_TERMS_FOR_FUZZY_CONTENT_FIELDS = 2

    STRATEGY_BOOSTS = {
        # Simple match strategy boosts
        ("simple_match", "title"): 1.0,
        ("simple_match", "author"): 0.8,
        ("simple_match", "content"): 1.0,
        # Simple match sub-strategy multipliers
        ("simple_match_and", "all"): 0.5,
        ("simple_match_fuzzy", "all"): 0.2,
        # Phrase strategy boosts
        ("phrase", "title"): 0.6,
        ("phrase", "abstract"): 0.75,
        ("phrase", "content"): 0.6,
        # Prefix strategy boosts
        ("prefix", "all"): 0.5,
        # Fuzzy strategy boosts (absolute values, not multipliers)
        ("fuzzy", "title"): 2.0,
        ("fuzzy", "author"): 2.0,
        ("fuzzy", "content"): None,
    }
    TITLE_FIELDS = [
        FieldConfig(
            "paper_title", boost=3.0, query_types=["phrase", "prefix", "fuzzy"]
        ),
        FieldConfig("title", boost=3.0, query_types=["phrase", "prefix", "fuzzy"]),
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
        FieldConfig("abstract", boost=1.0, query_types=["phrase", "fuzzy"]),
        FieldConfig("renderable_text", boost=1.0, query_types=["fuzzy"]),
    ]

    def __init__(self, query: str):
        self.query = query
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
        try:
            if DOI.is_doi(self.query):
                normalized_doi = DOI.normalize_doi(self.query)
                self.should_clauses.append(
                    Q("term", doi={"value": normalized_doi, "boost": 8.0})
                )
        except Exception:
            pass

    def add_author_title_combination_strategy(self) -> "DocumentQueryBuilder":
        truncated_query = self._limit_query_to_max_words(
            self.query, self.MAX_QUERY_WORDS_FOR_AUTHOR_TITLE_COMBO
        )

        author_fields = []
        title_fields = []
        for field in self.AUTHOR_FIELDS:
            author_fields.append(field.get_boosted_name())
        for field in self.TITLE_FIELDS:
            title_fields.append(field.get_boosted_name())

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

        if author_queries and title_queries:
            author_match = Q("bool", should=author_queries, minimum_should_match=1)
            title_match = Q("bool", should=title_queries, minimum_should_match=1)
            author_title_combo = Q("bool", must=[author_match, title_match], boost=15.0)
            self.should_clauses.append(author_title_combo)

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
                field_slop = 2 if field.name == "abstract" else slop
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
        self, fields: list[FieldConfig], max_expansions: int = 20
    ) -> "DocumentQueryBuilder":
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
        if "fuzzy" not in (field.query_types or []):
            return True
        return restrict_to_author_title_only and field.name not in author_title_names

    def _get_fuzzy_boost(self, field: FieldConfig) -> float:
        if field.name in ["paper_title", "title"]:
            return self.STRATEGY_BOOSTS[("fuzzy", "title")]
        if "authors" in field.name:
            return self.STRATEGY_BOOSTS[("fuzzy", "author")]
        return field.boost

    def _format_boosted_field_name(self, field_name: str, boost: float) -> str:
        if math.isclose(boost, 1.0):
            return field_name
        if math.isclose(boost, round(boost)):
            return f"{field_name}^{int(round(boost))}"
        return f"{field_name}^{boost}"

    def add_fuzzy_strategy(
        self, fields: list[FieldConfig], operator: str = "and"
    ) -> "DocumentQueryBuilder":
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
        self, fields: list[FieldConfig]
    ) -> "DocumentQueryBuilder":
        field_list = []
        for field in fields:
            if "fuzzy" in (field.query_types or []):
                if field.name in ["paper_title", "title"]:
                    fuzzy_boost = 4.0
                elif "authors" in field.name:
                    fuzzy_boost = 2.0
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
                fuzziness=1,
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
                boost=2.5,
            )
            self.should_clauses.append(author_query)
        return self

    def _get_field_category(self, field: FieldConfig) -> str:
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
            self.should_clauses.append(
                Q(
                    "match_phrase",
                    **{field.name: {"query": self.query, "boost": base_boost}},
                )
            )
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
        all_fields = []
        for field in self.AUTHOR_FIELDS + self.TITLE_FIELDS:
            all_fields.append(field.get_boosted_name())

        fallback_query = Q(
            "multi_match",
            query=self.query,
            type="cross_fields",
            operator="or",
            fields=all_fields,
            boost=0.2,
        )
        self.should_clauses.append(fallback_query)
        return self

    def build(self) -> Q:
        return Q("bool", should=self.should_clauses, minimum_should_match=1)

    def build_with_popularity_boost(
        self, popularity_config: PopularityConfig | None = None
    ) -> Q:
        text_query = self.build()

        if popularity_config is None:
            popularity_config = DEFAULT_POPULARITY_CONFIG

        if not popularity_config.enabled:
            return text_query

        functions = []

        if popularity_config.weight > 0:
            functions.append(
                {
                    "field_value_factor": {
                        "field": "hot_score_v2",
                        "factor": popularity_config.weight,
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
            score_mode="sum",
            boost_mode=popularity_config.boost_mode,
        )


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
                "last_name^4",
                "headline^2",
                "description^1",
            ],
            type="best_fields",
            fuzziness="AUTO",
            operator="or",
        )


class UnifiedSearchQueryBuilder:
    def __init__(self, popularity_config: PopularityConfig | None = None):
        self.popularity_config = popularity_config or DEFAULT_POPULARITY_CONFIG

    def _configure_document_builder(self, query: str) -> DocumentQueryBuilder:
        builder = DocumentQueryBuilder(query)
        is_single_word = DocumentQueryBuilder._is_single_word_query(query)

        title_fields = DocumentQueryBuilder.TITLE_FIELDS
        author_fields = DocumentQueryBuilder.AUTHOR_FIELDS
        content_fields = DocumentQueryBuilder.CONTENT_FIELDS

        builder.should_clauses.append(
            Q(
                "multi_match",
                query=query,
                fields=["paper_title^7", "title^7"],
                type="best_fields",
                operator="and",
                boost=8.0,
            )
        )

        builder = (
            builder.add_simple_match_strategy(title_fields)
            .add_simple_match_strategy(author_fields)
            .add_author_name_strategy()
            .add_phrase_strategy(title_fields + content_fields, slop=1)
        )

        if not is_single_word:
            builder = builder.add_author_title_combination_strategy()

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

        return builder.add_cross_field_fallback_strategy()

    def build_document_query(self, query: str) -> Q:
        return self._configure_document_builder(query).build()

    def build_document_query_with_popularity(
        self, query: str, popularity_config: PopularityConfig | None = None
    ) -> Q:
        builder = self._configure_document_builder(query)
        config = popularity_config or self.popularity_config
        return builder.build_with_popularity_boost(config)

    def build_person_query(self, query: str) -> Q:
        return PersonQueryBuilder(query).build()
