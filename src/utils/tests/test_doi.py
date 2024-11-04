import unittest

import researchhub.settings as settings

from ..doi import DOI


class TestDOI(unittest.TestCase):
    def test_init_with_no_params(self):
        doi = DOI()
        self.assertIsNotNone(doi.base_doi)
        self.assertIsNotNone(doi.doi)
        self.assertEqual(doi.doi, doi.base_doi)

    def test_init_with_base_doi(self):
        base = "10.1234/test"
        doi = DOI(base_doi=base)
        self.assertEqual(doi.base_doi, base)
        self.assertEqual(doi.doi, base)

    def test_init_with_version(self):
        version = 1
        doi = DOI(version=version)
        self.assertTrue(doi.doi.endswith(f".{version}"))

    def test_init_with_version_and_base_doi(self):
        base = "10.1234/test"
        version = 1
        doi = DOI(base_doi=base, version=version)
        self.assertEqual(doi.doi, f"{base}.{version}")

    def test_generate_base_doi(self):
        doi = DOI()
        generated = doi._generate_base_doi()
        self.assertTrue(generated.startswith(settings.CROSSREF_DOI_PREFIX))
        self.assertTrue(
            len(generated)
            == settings.CROSSREF_DOI_SUFFIX_LENGTH + len(settings.CROSSREF_DOI_PREFIX)
        )
