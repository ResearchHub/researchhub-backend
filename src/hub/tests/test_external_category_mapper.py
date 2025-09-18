"""
Tests for the ExternalCategoryMapper for arXiv, bioRxiv, MedRxiv, and ChemRxiv mappings.
"""

from django.test import TestCase

from hub.mappers import ExternalCategoryMapper
from hub.models import Hub


class ExternalCategoryMapperTestCase(TestCase):
    """Test the ExternalCategoryMapper functionality."""

    def setUp(self):
        """Set up test environment with some basic hubs."""
        # Create some test hubs that are commonly used across tests
        self.cs_hub = Hub.objects.create(
            name="Computer Science", description="Computer Science research"
        )
        self.ml_hub = Hub.objects.create(
            name="Machine Learning", description="Machine Learning research"
        )
        self.bio_hub = Hub.objects.create(
            name="Biology", description="Biology research"
        )
        self.neuro_hub = Hub.objects.create(
            name="Neuroscience", description="Neuroscience research"
        )
        self.eng_hub = Hub.objects.create(
            name="Engineering", description="Engineering research"
        )
        self.bioeng_hub = Hub.objects.create(
            name="Bioengineering", description="Bioengineering research"
        )

    def test_returns_empty_list_when_category_not_mapped(self):
        """
        Test that unmapped categories return an empty list.

        When a category doesn't exist in our mappings, the mapper should
        return an empty list rather than raising an error or returning None.
        """
        # Test unmapped category for each source
        sources_and_unmapped = [
            ("arxiv", "xyz.INVALID"),
            ("biorxiv", "nonexistent-category"),
            ("medrxiv", "fake-specialty"),
            ("chemrxiv", "imaginary-chemistry"),
        ]

        for source, unmapped_category in sources_and_unmapped:
            with self.subTest(source=source):
                result = ExternalCategoryMapper.map(unmapped_category, source=source)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 0)

    def test_returns_empty_list_for_empty_input(self):
        """
        Test that empty string input returns an empty list.

        This ensures the mapper handles edge cases gracefully without errors.
        """
        result = ExternalCategoryMapper.map("", source="arxiv")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_mappings_are_case_insensitive(self):
        """
        Test that category mappings work regardless of case.

        Users might input categories in various cases (UPPERCASE, lowercase, MiXeD),
        and all should map to the same hubs.
        """
        # Test arXiv with different cases
        arxiv_results = [
            ExternalCategoryMapper.map("CS.LG", source="arxiv"),
            ExternalCategoryMapper.map("cs.lg", source="arxiv"),
            ExternalCategoryMapper.map("Cs.Lg", source="arxiv"),
        ]

        # All should return the same hubs
        for i in range(1, len(arxiv_results)):
            self.assertEqual(
                set(h.name for h in arxiv_results[0]),
                set(h.name for h in arxiv_results[i]),
                "Case variations should map to same hubs",
            )

    def test_whitespace_is_trimmed_from_input(self):
        """
        Test that extra whitespace in categories is handled correctly.

        Users might accidentally include spaces, and these should be trimmed.
        """
        # Test with and without whitespace
        result_with_spaces = ExternalCategoryMapper.map("  cs.LG  ", source="arxiv")
        result_without = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        self.assertEqual(
            set(h.name for h in result_with_spaces),
            set(h.name for h in result_without),
            "Whitespace should not affect mapping",
        )

    def test_unknown_source_returns_empty_list_with_warning(self):
        """
        Test that unknown sources return empty list and log a warning.

        If someone tries to use an unsupported source (e.g., 'pubmed'),
        we should warn them and return an empty list rather than crash.
        """
        with self.assertLogs(
            "hub.mappers.external_category_mapper", level="WARNING"
        ) as cm:
            result = ExternalCategoryMapper.map("any.category", source="unknown-source")

        # Check warning was logged
        self.assertIn("Unknown source: unknown-source", cm.output[0])

        # Check empty list returned
        self.assertEqual(result, [])

    def test_arxiv_category_mapping_returns_correct_hubs(self):
        """
        Test that arXiv categories map to Computer Science and subcategory hubs.

        Example: 'cs.LG' should map to ['Computer Science', 'Machine Learning']
        """
        test_mappings = [
            ("cs.LG", ["Computer Science", "Machine Learning"]),
            ("cs.AI", ["Computer Science", "Artificial Intelligence"]),
        ]

        # Create necessary hubs
        Hub.objects.create(name="Artificial Intelligence", description="AI research")

        for arxiv_category, expected_hub_names in test_mappings:
            with self.subTest(category=arxiv_category):
                result = ExternalCategoryMapper.map(arxiv_category, source="arxiv")

                self.assertEqual(len(result), len(expected_hub_names))
                result_names = [hub.name for hub in result]

                for expected_name in expected_hub_names:
                    self.assertIn(expected_name, result_names)

    def test_biorxiv_category_mapping_returns_correct_hubs(self):
        """
        Test that bioRxiv categories map to Biology/Medicine and subcategory hubs.

        Example: 'neuroscience' should map to ['Biology', 'Neuroscience']
        """
        test_mappings = [
            ("neuroscience", ["Biology", "Neuroscience"]),
            ("bioengineering", ["Engineering", "Bioengineering"]),
        ]

        for biorxiv_category, expected_hub_names in test_mappings:
            with self.subTest(category=biorxiv_category):
                result = ExternalCategoryMapper.map(biorxiv_category, source="biorxiv")

                self.assertEqual(len(result), len(expected_hub_names))
                result_names = [hub.name for hub in result]

                for expected_name in expected_hub_names:
                    self.assertIn(expected_name, result_names)

    def test_medrxiv_category_mapping_returns_correct_hubs(self):
        """
        Test that MedRxiv medical specialties map to Medicine and specialty hubs.

        Example: 'cardiology' should map to ['Medicine', 'Cardiology']
        """
        # Create necessary hubs
        Hub.objects.create(name="Medicine", description="Medicine research")
        Hub.objects.create(name="Cardiology", description="Cardiology research")
        Hub.objects.create(name="Surgery", description="Surgery research")

        test_mappings = [
            ("cardiovascular medicine", ["Medicine", "Cardiology"]),
            ("surgery", ["Medicine", "Surgery"]),
        ]

        for medrxiv_category, expected_hub_names in test_mappings:
            with self.subTest(category=medrxiv_category):
                result = ExternalCategoryMapper.map(medrxiv_category, source="medrxiv")

                self.assertEqual(len(result), len(expected_hub_names))
                result_names = [hub.name for hub in result]

                for expected_name in expected_hub_names:
                    self.assertIn(expected_name, result_names)

    def test_chemrxiv_category_mapping_returns_correct_hubs(self):
        """
        Test that ChemRxiv chemistry fields map to Chemistry and subfield hubs.

        Example: 'organic chemistry' should map to ['Chemistry', 'Organic Chemistry']
        """
        # Create necessary hubs
        Hub.objects.create(name="Chemistry", description="Chemistry research")
        Hub.objects.create(
            name="Organic Chemistry", description="Organic Chemistry research"
        )
        Hub.objects.create(name="Catalysis", description="Catalysis research")

        test_mappings = [
            ("organic chemistry", ["Chemistry", "Organic Chemistry"]),
            ("catalysis", ["Chemistry", "Catalysis"]),
        ]

        for chemrxiv_category, expected_hub_names in test_mappings:
            with self.subTest(category=chemrxiv_category):
                result = ExternalCategoryMapper.map(
                    chemrxiv_category, source="chemrxiv"
                )

                self.assertEqual(len(result), len(expected_hub_names))
                result_names = [hub.name for hub in result]

                for expected_name in expected_hub_names:
                    self.assertIn(expected_name, result_names)

    def test_logs_warning_when_mapped_hub_not_found_in_database(self):
        """
        Test that a warning is logged when a mapped hub doesn't exist in the database.

        This helps identify when mappings reference hubs that haven't been created yet.
        The mapping should still return any hubs that do exist.
        """
        # Delete the Machine Learning hub to simulate it not existing
        Hub.objects.filter(name="Machine Learning").delete()

        with self.assertLogs(
            "hub.mappers.external_category_mapper", level="WARNING"
        ) as cm:
            result = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        # Should log warning about missing hub
        self.assertTrue(
            any(
                "Hub not found in database: Machine Learning" in msg
                for msg in cm.output
            )
        )

        # Should still return the Computer Science hub that does exist
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Computer Science")

    def test_handles_multiple_hubs_with_same_name_gracefully(self):
        """
        Test that mapper handles duplicate hub names gracefully.

        In case of data integrity issues where multiple hubs have the same name,
        the mapper should log a warning but continue working.
        """
        # Create duplicate hub with same name
        Hub.objects.create(name="Machine Learning", description="Duplicate ML hub")

        with self.assertLogs(
            "hub.mappers.external_category_mapper", level="WARNING"
        ) as cm:
            result = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        # Should log warning about multiple hubs
        self.assertTrue(
            any(
                "Multiple hubs found with name: Machine Learning" in msg
                for msg in cm.output
            )
        )

        # Should still return results (first matching hub for each name)
        self.assertEqual(len(result), 2)
        hub_names = [hub.name for hub in result]
        self.assertIn("Computer Science", hub_names)
        self.assertIn("Machine Learning", hub_names)

    def test_cross_discipline_mappings_work_correctly(self):
        """
        Test that categories can map across traditional discipline boundaries.

        Some categories like 'biochemistry' in ChemRxiv should map to Biology hubs,
        not Chemistry hubs, reflecting the interdisciplinary nature of research.
        """
        # Create hubs for cross-discipline test
        Hub.objects.create(name="Biochemistry", description="Biochemistry research")
        Hub.objects.create(
            name="Biological Physics", description="Biological Physics research"
        )

        result = ExternalCategoryMapper.map("biochemistry", source="chemrxiv")
        result_names = [hub.name for hub in result]
        self.assertIn("Biology", result_names)
        self.assertIn("Biochemistry", result_names)

        result = ExternalCategoryMapper.map("physics.bio-ph", source="arxiv")
        result_names = [hub.name for hub in result]
        self.assertIn("Biology", result_names)
        self.assertIn("Biological Physics", result_names)

    def test_special_character_handling_in_categories(self):
        """
        Test that categories with special characters work correctly.

        Some MedRxiv categories include parenthetical descriptions.
        """
        # Create necessary hubs
        Hub.objects.create(name="Medicine", description="Medicine research")
        Hub.objects.create(name="Endocrinology", description="Endocrinology research")

        # Test MedRxiv category with parentheses
        result = ExternalCategoryMapper.map(
            "endocrinology (including diabetes mellitus and metabolic disease)",
            source="medrxiv",
        )

        self.assertEqual(len(result), 2)
        result_names = [hub.name for hub in result]
        self.assertIn("Medicine", result_names)
        self.assertIn("Endocrinology", result_names)
