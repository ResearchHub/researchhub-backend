from django.test import TestCase

from search.services.search_config import (
    DEFAULT_DOCUMENT_CONFIG,
    DEFAULT_PERSON_CONFIG,
    DocumentSearchConfig,
    FieldConfig,
    PersonSearchConfig,
)


class SearchConfigTests(TestCase):
    def test_field_config_boosted_name(self):
        self.assertEqual(FieldConfig("title", boost=3.0).get_boosted_name(), "title^3.0")
        self.assertEqual(FieldConfig("abstract", boost=1.0).get_boosted_name(), "abstract")

    def test_document_config_title_fields(self):
        config = DocumentSearchConfig()
        field_names = [f.name for f in config.title_fields]
        self.assertIn("paper_title", field_names)
        self.assertIn("title", field_names)

    def test_document_config_author_fields(self):
        config = DocumentSearchConfig()
        self.assertEqual(len(config.author_fields), 6)

    def test_person_config_fields(self):
        config = PersonSearchConfig()
        fields = config.get_fields_with_boosts()
        self.assertEqual(len(fields), 5)
        self.assertIn("full_name^5.0", fields)

    def test_default_configs_exist(self):
        self.assertIsInstance(DEFAULT_DOCUMENT_CONFIG, DocumentSearchConfig)
        self.assertIsInstance(DEFAULT_PERSON_CONFIG, PersonSearchConfig)
