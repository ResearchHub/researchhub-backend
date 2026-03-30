from unittest import TestCase


class TestBiorxivServerNull(TestCase):
    """Validates the (value or default).lower() pattern used in BioRxivBaseMapper."""

    def test_server_field_none_uses_default(self):
        default_server = "biorxiv"
        record = {"server": None, "doi": "10.1234/test"}
        server = (record.get("server") or default_server).lower()
        self.assertEqual(server, "biorxiv")

    def test_server_field_present(self):
        default_server = "biorxiv"
        record = {"server": "MedRxiv", "doi": "10.1234/test"}
        server = (record.get("server") or default_server).lower()
        self.assertEqual(server, "medrxiv")

    def test_server_field_missing(self):
        default_server = "biorxiv"
        record = {"doi": "10.1234/test"}
        server = (record.get("server") or default_server).lower()
        self.assertEqual(server, "biorxiv")
