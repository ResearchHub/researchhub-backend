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
        # Clear the mapper cache before each test
        ExternalCategoryMapper.clear_cache()

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

    def test_hub_caching_mechanism(self):
        """Test that hub caching works correctly."""
        # Test that cache initialization only happens once
        ExternalCategoryMapper.clear_cache()

        # Track database calls
        with patch.object(Hub.objects, "filter") as mock_filter:
            with patch.object(HubCategory.objects, "all") as mock_cat_all:
                # Set up return values
                mock_filter.return_value.select_related.return_value = []
                mock_cat_all.return_value = []

                # Cache should be None initially
                self.assertIsNone(ExternalCategoryMapper._hub_cache)
                self.assertIsNone(ExternalCategoryMapper._hub_category_cache)

                # First map call should initialize cache
                ExternalCategoryMapper.map("cs.LG", source="arxiv")

                # Cache should now be initialized
                self.assertIsNotNone(ExternalCategoryMapper._hub_cache)
                self.assertIsNotNone(ExternalCategoryMapper._hub_category_cache)
                self.assertEqual(mock_filter.call_count, 1)
                self.assertEqual(mock_cat_all.call_count, 1)

                # Second call should use existing cache
                ExternalCategoryMapper.map("cs.AI", source="arxiv")

                # Database should not be called again
                self.assertEqual(mock_filter.call_count, 1)
                self.assertEqual(mock_cat_all.call_count, 1)

    def test_cache_contains_all_hubs(self):
        """Test that all hubs are loaded into memory cache."""
        # Initialize cache
        ExternalCategoryMapper.initialize_hub_cache()

        # Check that our test hubs are in cache
        self.assertIn(
            (
                f"subcategory:{self.cs_category.category_name.lower()}:"
                f"{self.ml_hub.name.lower()}"
            ),
            ExternalCategoryMapper._hub_cache,
        )
        self.assertIn(
            (
                f"subcategory:{self.bio_category.category_name.lower()}:"
                f"{self.neuro_hub.name.lower()}"
            ),
            ExternalCategoryMapper._hub_cache,
        )

        # Check that HubCategories are in cache
        self.assertIn(
            self.cs_category.category_name.lower(),
            ExternalCategoryMapper._hub_category_cache,
        )
        self.assertIn(
            self.bio_category.category_name.lower(),
            ExternalCategoryMapper._hub_category_cache,
        )

    def test_mapping_cache_works(self):
        """Test that mapping results are cached."""
        # Clear cache
        ExternalCategoryMapper.clear_cache()

        # Map same category twice
        result1 = ExternalCategoryMapper.map("cs.LG", source="arxiv")
        result2 = ExternalCategoryMapper.map("cs.LG", source="arxiv")

        # Should return same object from cache
        self.assertEqual(result1, result2)

        # Check cache key exists
        cache_key = "arxiv:cs.lg"
        self.assertIn(cache_key, ExternalCategoryMapper._mapping_cache)

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

        # Clear cache to pick up new hubs
        ExternalCategoryMapper.clear_cache()

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

        # Clear cache to pick up new hubs
        ExternalCategoryMapper.clear_cache()

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
