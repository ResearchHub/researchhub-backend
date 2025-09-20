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
        # Create some test hubs with proper slugs
        # The Hub model's save() method will auto-generate slugs from names
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

    def test_category_normalization(self):
        """
        Test that category input is properly normalized (case-insensitive and whitespace-trimmed).

        Users might input categories in various cases with extra whitespace.
        """
        # Test different variations that should all map to the same result
        variations = [
            "CS.LG",
            "cs.lg",
            "Cs.Lg",
            "  cs.LG  ",
            "\tCS.LG\n",
        ]

        results = [
            ExternalCategoryMapper.map(var, source="arxiv") for var in variations
        ]

        # All should return the same hubs
        base_result = set(h.name for h in results[0])
        for i in range(1, len(results)):
            self.assertEqual(
                base_result,
                set(h.name for h in results[i]),
                f"Variation '{variations[i]}' should map to same hubs as '{variations[0]}'",
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
        Hub.objects.filter(slug="machine-learning").delete()

        with self.assertLogs(
            "hub.mappers.external_category_mapper", level="WARNING"
        ) as cm:
            result = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        # Should log warning about missing hub
        self.assertTrue(
            any(
                "Hub not found in database: machine-learning" in msg
                for msg in cm.output
            )
        )

        # Should still return the Computer Science hub that does exist
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Computer Science")

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

        # Test ChemRxiv biochemistry -> Biology
        result = ExternalCategoryMapper.map("biochemistry", source="chemrxiv")
        result_names = [hub.name for hub in result]
        self.assertIn("Biology", result_names)
        self.assertIn("Biochemistry", result_names)

        # Test arXiv physics.bio-ph -> Biology
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
