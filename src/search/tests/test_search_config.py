"""
Tests for search configuration module.

These tests verify the configuration dataclasses and their helper methods
without requiring OpenSearch mocks.
"""

from unittest import TestCase

from search.services.search_config import (
    DEFAULT_DOCUMENT_CONFIG,
    DEFAULT_PERSON_CONFIG,
    DEFAULT_POPULARITY_CONFIG,
    DocumentSearchConfig,
    FieldBoosts,
    FieldConfig,
    PersonSearchConfig,
    PopularityConfig,
    QueryTypeConfig,
)


class FieldConfigTests(TestCase):

    def test_get_boosted_name_with_boost(self):
        field = FieldConfig("paper_title", boost=3.0)
        self.assertEqual(field.get_boosted_name(), "paper_title^3.0")

    def test_get_boosted_name_no_boost(self):
        field = FieldConfig("abstract", boost=1.0)
        self.assertEqual(field.get_boosted_name(), "abstract")

    def test_get_boosted_name_near_one(self):
        field = FieldConfig("abstract", boost=1.0000000001)
        self.assertEqual(field.get_boosted_name(), "abstract")

    def test_default_boost_is_one(self):
        field = FieldConfig("test_field")
        self.assertEqual(field.boost, 1.0)
        self.assertEqual(field.get_boosted_name(), "test_field")

    def test_query_types_default_none(self):
        field = FieldConfig("test_field")
        self.assertIsNone(field.query_types)

    def test_query_types_can_be_set(self):
        field = FieldConfig("title", query_types=["phrase", "prefix"])
        self.assertEqual(field.query_types, ["phrase", "prefix"])


class PopularityConfigTests(TestCase):

    def test_default_enabled(self):
        config = PopularityConfig()
        self.assertTrue(config.enabled)

    def test_can_disable(self):
        config = PopularityConfig(enabled=False)
        self.assertFalse(config.enabled)

    def test_default_weights(self):
        config = PopularityConfig()
        self.assertEqual(config.citations_weight, 1.5)
        self.assertEqual(config.discussion_weight, 1.2)
        self.assertEqual(config.hot_score_weight, 1.0)
        self.assertEqual(config.score_weight, 0.8)

    def test_weight_hierarchy_citations_gt_discussions_gt_hot_score_gt_score(self):
        config = PopularityConfig()
        self.assertGreater(config.citations_weight, config.discussion_weight)
        self.assertGreater(config.discussion_weight, config.hot_score_weight)
        self.assertGreater(config.hot_score_weight, config.score_weight)

    def test_custom_weights(self):
        config = PopularityConfig(citations_weight=2.0, discussion_weight=0.5)
        self.assertEqual(config.citations_weight, 2.0)
        self.assertEqual(config.discussion_weight, 0.5)

    def test_default_boost_mode_is_multiply(self):
        config = PopularityConfig()
        self.assertEqual(config.boost_mode, "multiply")

    def test_default_score_mode_is_sum(self):
        config = PopularityConfig()
        self.assertEqual(config.score_mode, "sum")


class FieldBoostsTests(TestCase):

    def test_default_title_boost(self):
        boosts = FieldBoosts()
        self.assertEqual(boosts.title, 3.0)

    def test_author_boost_hierarchy_full_gt_last_gt_first(self):
        boosts = FieldBoosts()
        self.assertGreater(boosts.author_full_name, boosts.author_last_name)
        self.assertGreater(boosts.author_last_name, boosts.author_first_name)

    def test_content_boosts_are_baseline(self):
        boosts = FieldBoosts()
        self.assertEqual(boosts.abstract, 1.0)
        self.assertEqual(boosts.renderable_text, 1.0)


class QueryTypeConfigTests(TestCase):

    def test_title_supports_phrase_prefix_fuzzy(self):
        config = QueryTypeConfig()
        self.assertIn("phrase", config.title_query_types)
        self.assertIn("prefix", config.title_query_types)
        self.assertIn("fuzzy", config.title_query_types)

    def test_author_supports_cross_fields(self):
        config = QueryTypeConfig()
        self.assertIn("cross_fields", config.author_query_types)

    def test_content_supports_fuzzy_only(self):
        config = QueryTypeConfig()
        self.assertEqual(config.content_query_types, ["fuzzy"])


class DocumentSearchConfigTests(TestCase):

    def test_title_fields_returns_paper_title_and_title(self):
        config = DocumentSearchConfig()
        fields = config.title_fields
        field_names = [f.name for f in fields]
        self.assertIn("paper_title", field_names)
        self.assertIn("title", field_names)
        self.assertEqual(len(fields), 2)

    def test_title_fields_have_configured_boost(self):
        config = DocumentSearchConfig()
        for field in config.title_fields:
            self.assertEqual(field.boost, config.field_boosts.title)

    def test_author_fields_includes_raw_authors_and_authors_prefixes(self):
        config = DocumentSearchConfig()
        fields = config.author_fields
        field_names = [f.name for f in fields]

        self.assertIn("raw_authors.full_name", field_names)
        self.assertIn("raw_authors.last_name", field_names)
        self.assertIn("raw_authors.first_name", field_names)
        self.assertIn("authors.full_name", field_names)
        self.assertIn("authors.last_name", field_names)
        self.assertIn("authors.first_name", field_names)
        self.assertEqual(len(fields), 6)

    def test_author_fields_have_hierarchical_boosts(self):
        config = DocumentSearchConfig()
        boosts = config.field_boosts

        for field in config.author_fields:
            if "full_name" in field.name:
                self.assertEqual(field.boost, boosts.author_full_name)
            elif "last_name" in field.name:
                self.assertEqual(field.boost, boosts.author_last_name)
            elif "first_name" in field.name:
                self.assertEqual(field.boost, boosts.author_first_name)

    def test_content_fields_returns_abstract_and_renderable_text(self):
        config = DocumentSearchConfig()
        fields = config.content_fields
        field_names = [f.name for f in fields]
        self.assertIn("abstract", field_names)
        self.assertIn("renderable_text", field_names)
        self.assertEqual(len(fields), 2)

    def test_query_limits_are_sensible(self):
        config = DocumentSearchConfig()
        self.assertGreater(config.max_query_words_for_author_title_combo, 0)
        self.assertLessEqual(config.max_query_words_for_author_title_combo, 10)
        self.assertGreater(config.max_terms_for_fuzzy_content_fields, 0)
        self.assertLessEqual(config.max_terms_for_fuzzy_content_fields, 5)

    def test_dis_max_tie_breaker_in_valid_range(self):
        config = DocumentSearchConfig()
        self.assertGreaterEqual(config.dis_max_tie_breaker, 0.0)
        self.assertLessEqual(config.dis_max_tie_breaker, 1.0)

    def test_custom_field_boosts_propagate_to_field_configs(self):
        custom_boosts = FieldBoosts(title=5.0, author_full_name=4.0)
        config = DocumentSearchConfig(field_boosts=custom_boosts)

        for field in config.title_fields:
            self.assertEqual(field.boost, 5.0)

        for field in config.author_fields:
            if "full_name" in field.name:
                self.assertEqual(field.boost, 4.0)


class PersonSearchConfigTests(TestCase):

    def test_get_fields_with_boosts_returns_formatted_fields(self):
        config = PersonSearchConfig()
        fields = config.get_fields_with_boosts()

        self.assertIn(f"full_name^{config.full_name_boost}", fields)
        self.assertIn(f"first_name^{config.first_name_boost}", fields)
        self.assertIn(f"last_name^{config.last_name_boost}", fields)
        self.assertIn(f"headline^{config.headline_boost}", fields)
        self.assertIn(f"description^{config.description_boost}", fields)

    def test_boost_hierarchy_name_gt_headline_gt_description(self):
        config = PersonSearchConfig()
        self.assertGreater(config.full_name_boost, config.headline_boost)
        self.assertGreater(config.headline_boost, config.description_boost)

    def test_default_query_settings(self):
        config = PersonSearchConfig()
        self.assertEqual(config.fuzziness, "AUTO")
        self.assertEqual(config.query_type, "best_fields")
        self.assertEqual(config.operator, "or")

    def test_custom_boosts_reflected_in_field_list(self):
        config = PersonSearchConfig(full_name_boost=10.0)
        fields = config.get_fields_with_boosts()
        self.assertIn("full_name^10.0", fields)


class DefaultConfigInstancesTests(TestCase):

    def test_default_document_config_is_document_search_config(self):
        self.assertIsInstance(DEFAULT_DOCUMENT_CONFIG, DocumentSearchConfig)

    def test_default_person_config_is_person_search_config(self):
        self.assertIsInstance(DEFAULT_PERSON_CONFIG, PersonSearchConfig)

    def test_default_popularity_config_is_popularity_config(self):
        self.assertIsInstance(DEFAULT_POPULARITY_CONFIG, PopularityConfig)

    def test_default_popularity_config_is_enabled(self):
        self.assertTrue(DEFAULT_POPULARITY_CONFIG.enabled)

    def test_default_configs_are_singletons(self):
        from search.services.search_config import DEFAULT_DOCUMENT_CONFIG as config2

        self.assertIs(DEFAULT_DOCUMENT_CONFIG, config2)
