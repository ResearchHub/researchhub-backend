"""
Tests for the ExternalCategoryMapper for arXiv and bioRxiv mappings.
"""

from unittest.mock import patch

from django.test import TestCase

from hub.mappers import ExternalCategoryMapper
from hub.mappers.hub_mapping import HubMapping
from hub.models import Hub, HubCategory


class ExternalCategoryMapperTestCase(TestCase):
    """Test the ExternalCategoryMapper functionality."""

    def setUp(self):
        """Set up test environment."""

        # Create some test HubCategories
        self.cs_category = HubCategory.objects.create(category_name="Computer Science")
        self.bio_category = HubCategory.objects.create(category_name="Biology")
        self.eng_category = HubCategory.objects.create(category_name="Engineering")

        # Create some subcategory hubs
        self.ml_hub = Hub.objects.create(
            name="Machine Learning",
            namespace="subcategory",
            category=self.cs_category,
        )
        self.neuro_hub = Hub.objects.create(
            name="Neuroscience",
            namespace="subcategory",
            category=self.bio_category,
        )
        self.bioeng_hub = Hub.objects.create(
            name="Bioengineering",
            namespace="subcategory",
            category=self.eng_category,
        )

    def test_unmapped_biorxiv_category(self):
        """Test what happens when an unmapped bioRxiv category is provided."""
        # Use a category that doesn't exist in our mappings
        result = ExternalCategoryMapper.map("nonexistent-category", source="biorxiv")

        # Should return empty HubMapping
        self.assertIsInstance(result, HubMapping)
        self.assertIsNone(result.hub_category)
        self.assertIsNone(result.subcategory_hub)

    def test_arxiv_input_mapping(self):
        """Test mapping of arXiv categories."""
        # Test a known arXiv category
        result = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        self.assertIsInstance(result, HubMapping)
        self.assertIsNotNone(result.hub_category)
        self.assertEqual(result.hub_category.category_name, "Computer Science")
        self.assertIsNotNone(result.subcategory_hub)
        self.assertEqual(result.subcategory_hub.name, "Machine Learning")

    def test_biorxiv_input_mapping(self):
        """Test mapping of bioRxiv categories."""
        # Test a known bioRxiv category
        result = ExternalCategoryMapper.map("neuroscience", source="biorxiv")

        self.assertIsInstance(result, HubMapping)
        self.assertIsNotNone(result.hub_category)
        self.assertEqual(result.hub_category.category_name, "Biology")
        self.assertIsNotNone(result.subcategory_hub)
        self.assertEqual(result.subcategory_hub.name, "Neuroscience")

    def test_empty_input_handling(self):
        """Test handling of empty input."""
        # Test empty string
        result = ExternalCategoryMapper.map("", source="arxiv")

        self.assertIsInstance(result, HubMapping)
        self.assertIsNone(result.hub_category)
        self.assertIsNone(result.subcategory_hub)

    def test_case_insensitive_mapping(self):
        """Test that mappings are case-insensitive."""
        # Test with different cases for arXiv
        result1 = ExternalCategoryMapper.map("CS.LG", source="arxiv")
        result2 = ExternalCategoryMapper.map("cs.lg", source="arxiv")
        result3 = ExternalCategoryMapper.map("Cs.Lg", source="arxiv")

        # All should map to the same hubs
        self.assertEqual(result1.hub_category, result2.hub_category)
        self.assertEqual(result2.hub_category, result3.hub_category)
        self.assertEqual(result1.subcategory_hub, result2.subcategory_hub)

        # Test with MedRxiv
        result4 = ExternalCategoryMapper.map("EPIDEMIOLOGY", source="medrxiv")
        result5 = ExternalCategoryMapper.map("epidemiology", source="medrxiv")
        self.assertEqual(result4.hub_category, result5.hub_category)
        self.assertEqual(result4.subcategory_hub, result5.subcategory_hub)

        # Test with ChemRxiv
        result6 = ExternalCategoryMapper.map("ORGANIC CHEMISTRY", source="chemrxiv")
        result7 = ExternalCategoryMapper.map("organic chemistry", source="chemrxiv")
        self.assertEqual(result6.hub_category, result7.hub_category)
        self.assertEqual(result6.subcategory_hub, result7.subcategory_hub)

    def test_database_queries(self):
        """Test that mapper queries the database correctly."""
        # Test that mapper queries database for each mapping
        with patch.object(HubCategory.objects, "get") as mock_cat_get:
            with patch.object(Hub.objects, "get") as mock_hub_get:
                # Set up return values
                mock_cat = HubCategory(category_name="Computer Science")
                mock_hub = Hub(name="Machine Learning", namespace="subcategory")
                mock_cat_get.return_value = mock_cat
                mock_hub_get.return_value = mock_hub

                # First map call
                ExternalCategoryMapper.map("cs.LG", source="arxiv")
                self.assertEqual(mock_cat_get.call_count, 1)
                self.assertEqual(mock_hub_get.call_count, 1)

                # Second call should also query database
                ExternalCategoryMapper.map("cs.LG", source="arxiv")
                self.assertEqual(mock_cat_get.call_count, 2)
                self.assertEqual(mock_hub_get.call_count, 2)

    def test_unknown_source_defaults_to_arxiv(self):
        """Test that unknown source defaults to arxiv with warning."""
        with self.assertLogs(
            "hub.mappers.external_category_mapper", level="WARNING"
        ) as cm:
            result = ExternalCategoryMapper.map("cs.LG", source="unknown")

        # Should log warning
        self.assertIn("Unknown source: unknown", cm.output[0])

        # Should still map using arxiv
        self.assertIsNotNone(result.hub_category)

    def test_specific_mappings(self):
        """Test specific mappings to ensure they work correctly."""
        test_cases = [
            # (category, source, expected_category, expected_subcategory)
            # ArXiv mappings
            ("cs.AI", "arxiv", "Computer Science", "Artificial Intelligence"),
            ("math.CO", "arxiv", "Mathematics", "Combinatorics"),
            ("physics.bio-ph", "arxiv", "Biology", "Biological Physics"),
            ("q-bio.NC", "arxiv", "Biology", "Neuroscience"),
            # BioRxiv mappings
            ("cell biology", "biorxiv", "Biology", "Cell Biology"),
            ("epidemiology", "biorxiv", "Medicine", "Epidemiology"),
            ("bioengineering", "biorxiv", "Engineering", "Bioengineering"),
            # MedRxiv mappings
            ("cardiovascular medicine", "medrxiv", "Medicine", "Cardiology"),
            ("surgery", "medrxiv", "Medicine", "Surgery"),
            ("public and global health", "medrxiv", "Medicine", "Public Health"),
            # ChemRxiv mappings
            ("organic chemistry", "chemrxiv", "Chemistry", "Organic Chemistry"),
            ("catalysis", "chemrxiv", "Chemistry", "Catalysis"),
            (
                "computational chemistry and modeling",
                "chemrxiv",
                "Chemistry",
                "Computational Chemistry",
            ),
        ]

        # Create the necessary hubs for testing
        for _, _, cat_name, subcat_name in test_cases:
            # Ensure HubCategory exists
            hub_cat, _ = HubCategory.objects.get_or_create(
                category_name=cat_name,
                defaults={"category_name": cat_name},
            )

            if subcat_name:
                # Ensure subcategory hub exists
                Hub.objects.get_or_create(
                    name=subcat_name,
                    namespace="subcategory",
                    defaults={
                        "category": hub_cat,
                        "description": f"{subcat_name} subcategory",
                    },
                )

        # Test each mapping
        for category, source, expected_cat, expected_subcat in test_cases:
            result = ExternalCategoryMapper.map(category, source=source)

            if expected_cat:
                self.assertIsNotNone(
                    result.hub_category,
                    f"HubCategory should exist for {category} from {source}",
                )
                self.assertEqual(
                    result.hub_category.category_name,
                    expected_cat,
                    f"Wrong category for {category} from {source}",
                )

            if expected_subcat:
                self.assertIsNotNone(
                    result.subcategory_hub,
                    f"Subcategory hub should exist for {category} from {source}",
                )
                self.assertEqual(
                    result.subcategory_hub.name,
                    expected_subcat,
                    f"Wrong subcategory for {category} from {source}",
                )

    def test_whitespace_handling(self):
        """Test that whitespace in categories is handled correctly."""
        # Test arXiv with extra whitespace
        result1 = ExternalCategoryMapper.map("  cs.LG  ", source="arxiv")
        result2 = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        # Should produce same result
        self.assertEqual(result1.hub_category, result2.hub_category)
        self.assertEqual(result1.subcategory_hub, result2.subcategory_hub)

        # Test bioRxiv with extra whitespace
        result3 = ExternalCategoryMapper.map("  neuroscience  ", source="biorxiv")
        result4 = ExternalCategoryMapper.map("neuroscience", source="biorxiv")

        # Should produce same result
        self.assertEqual(result3.hub_category, result4.hub_category)
        self.assertEqual(result3.subcategory_hub, result4.subcategory_hub)

        # Test MedRxiv with extra whitespace
        result5 = ExternalCategoryMapper.map("  epidemiology  ", source="medrxiv")
        result6 = ExternalCategoryMapper.map("epidemiology", source="medrxiv")

        # Should produce same result
        self.assertEqual(result5.hub_category, result6.hub_category)
        self.assertEqual(result5.subcategory_hub, result6.subcategory_hub)

        # Test ChemRxiv with extra whitespace
        result7 = ExternalCategoryMapper.map("  catalysis  ", source="chemrxiv")
        result8 = ExternalCategoryMapper.map("catalysis", source="chemrxiv")

        # Should produce same result
        self.assertEqual(result7.hub_category, result8.hub_category)
        self.assertEqual(result7.subcategory_hub, result8.subcategory_hub)

    def test_medrxiv_mapping(self):
        """Test MedRxiv category mapping."""
        # Create necessary categories (get_or_create to avoid duplicates)
        medicine_cat, _ = HubCategory.objects.get_or_create(category_name="Medicine")
        biology_cat, _ = HubCategory.objects.get_or_create(category_name="Biology")

        # Create necessary subcategories
        subcategories_to_create = [
            ("Epidemiology", medicine_cat),
            ("Sports Medicine", medicine_cat),
            ("Internal Medicine", medicine_cat),
            ("Psychiatry", medicine_cat),
            ("Pathology", biology_cat),
            ("Toxicology", biology_cat),
        ]

        for subcat_name, category in subcategories_to_create:
            Hub.objects.create(
                name=subcat_name,
                namespace="subcategory",
                category=category,
            )

        # Test various MedRxiv mappings
        test_cases = [
            ("epidemiology", "Medicine", "Epidemiology"),
            ("sports medicine", "Medicine", "Sports Medicine"),
            ("allergy and immunology", "Medicine", "Internal Medicine"),
            ("addiction medicine", "Medicine", "Psychiatry"),
            ("pathology", "Biology", "Pathology"),
            ("forensic medicine", "Biology", "Pathology"),
            ("toxicology", "Biology", "Toxicology"),
        ]

        for medrxiv_cat, expected_cat, expected_subcat in test_cases:
            with self.subTest(category=medrxiv_cat):
                result = ExternalCategoryMapper.map(medrxiv_cat, source="medrxiv")
                self.assertIsNotNone(result.hub_category)
                self.assertEqual(result.hub_category.category_name, expected_cat)
                self.assertIsNotNone(result.subcategory_hub)
                self.assertEqual(result.subcategory_hub.name, expected_subcat)

        # Test unmapped MedRxiv category
        result = ExternalCategoryMapper.map("nonexistent specialty", source="medrxiv")
        self.assertIsNone(result.hub_category)
        self.assertIsNone(result.subcategory_hub)

        # Test MedRxiv category with special characters
        result = ExternalCategoryMapper.map(
            "endocrinology (including diabetes mellitus and metabolic disease)",
            source="medrxiv",
        )
        self.assertIsNotNone(result.hub_category)
        self.assertEqual(result.hub_category.category_name, "Medicine")
        self.assertEqual(result.subcategory_hub.name, "Internal Medicine")

    def test_chemrxiv_mapping(self):
        """Test ChemRxiv category mapping."""
        # Create necessary category
        chemistry_cat, _ = HubCategory.objects.get_or_create(category_name="Chemistry")

        # Create necessary subcategories
        subcategories_to_create = [
            "Organic Chemistry",
            "Catalysis",
            "Polymer Chemistry",
            "Computational Chemistry",
        ]

        for subcat_name in subcategories_to_create:
            Hub.objects.create(
                name=subcat_name,
                namespace="subcategory",
                category=chemistry_cat,
            )

        # Test various ChemRxiv mappings
        test_cases = [
            ("organic chemistry", "Chemistry", "Organic Chemistry"),
            ("catalysis", "Chemistry", "Catalysis"),
            ("polymer science", "Chemistry", "Polymer Chemistry"),
            (
                "theoretical and computational chemistry",
                "Chemistry",
                "Computational Chemistry",
            ),
        ]

        for chemrxiv_cat, expected_cat, expected_subcat in test_cases:
            with self.subTest(category=chemrxiv_cat):
                result = ExternalCategoryMapper.map(chemrxiv_cat, source="chemrxiv")
                self.assertIsNotNone(result.hub_category)
                self.assertEqual(result.hub_category.category_name, expected_cat)
                self.assertIsNotNone(result.subcategory_hub)
                self.assertEqual(result.subcategory_hub.name, expected_subcat)

        # Test unmapped ChemRxiv category
        result = ExternalCategoryMapper.map("nonexistent chemistry", source="chemrxiv")
        self.assertIsNone(result.hub_category)
        self.assertIsNone(result.subcategory_hub)

        # Test ChemRxiv categories that map to other fields
        biology_cat, _ = HubCategory.objects.get_or_create(category_name="Biology")
        engineering_cat, _ = HubCategory.objects.get_or_create(
            category_name="Engineering"
        )

        # Create subcategories for cross-field mappings
        Hub.objects.get_or_create(
            name="Biochemistry",
            namespace="subcategory",
            defaults={"category": biology_cat},
        )
        Hub.objects.get_or_create(
            name="Chemical Engineering",
            namespace="subcategory",
            defaults={"category": engineering_cat},
        )

        # Test cross-field mappings
        result = ExternalCategoryMapper.map("biochemistry", source="chemrxiv")
        self.assertEqual(result.hub_category.category_name, "Biology")
        self.assertEqual(result.subcategory_hub.name, "Biochemistry")

        result = ExternalCategoryMapper.map(
            "chemical engineering and industrial chemistry", source="chemrxiv"
        )
        self.assertEqual(result.hub_category.category_name, "Engineering")
        self.assertEqual(result.subcategory_hub.name, "Chemical Engineering")
