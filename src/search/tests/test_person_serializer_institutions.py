from unittest import TestCase
from unittest.mock import patch

from search.serializers.person import PersonDocumentSerializer


class TestGetInstitutions(TestCase):

    def setUp(self):
        self.serializer = PersonDocumentSerializer()

    def _make_doc(self, institutions):
        return type("Doc", (), {"institutions": institutions})()

    @patch("search.serializers.person.AttrList", list)
    def test_valid_institutions(self):
        doc = self._make_doc([
            {"id": 1, "name": "MIT"},
            {"id": 2, "name": "Stanford"},
        ])
        result = self.serializer.get_institutions(doc)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "MIT")

    @patch("search.serializers.person.AttrList", list)
    def test_none_institution_skipped(self):
        doc = self._make_doc([None, {"id": 1, "name": "MIT"}])
        result = self.serializer.get_institutions(doc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "MIT")

    @patch("search.serializers.person.AttrList", list)
    def test_missing_name_key_uses_default(self):
        doc = self._make_doc([{"id": 1}])
        result = self.serializer.get_institutions(doc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "")

    def test_non_list_returns_none(self):
        doc = self._make_doc("not a list")
        result = self.serializer.get_institutions(doc)
        self.assertIsNone(result)

    @patch("search.serializers.person.AttrList", list)
    def test_empty_list(self):
        doc = self._make_doc([])
        result = self.serializer.get_institutions(doc)
        self.assertEqual(result, [])
