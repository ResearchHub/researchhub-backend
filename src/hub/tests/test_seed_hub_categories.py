"""
Tests for the seed_hub_categories management command.
"""

from django.core.management import call_command
from django.test import TestCase

from hub.management.commands.seed_hub_categories import Command as SeedCommand
from hub.models import Hub, HubCategory


class SeedHubCategoriesTestCase(TestCase):
    """Test the seed_hub_categories management command."""

    def setUp(self):
        """Set up test environment."""
        # Clear any existing data
        Hub.objects.all().delete()
        HubCategory.objects.all().delete()

    def test_categories_created_in_hub_category_model(self):
        """Test that categories are created in HubCategory model only."""
        # Run the seed command
        call_command("seed_hub_categories")

        # Get all master categories
        master_categories = SeedCommand.get_master_categories()

        # Check that all categories exist in HubCategory model
        for category_name in master_categories.keys():
            hub_category = HubCategory.objects.filter(
                category_name__iexact=category_name
            ).first()
            self.assertIsNotNone(
                hub_category, f"HubCategory '{category_name}' should exist"
            )

        # Check that NO category hubs exist in Hub model
        category_hubs = Hub.objects.filter(namespace="category")
        self.assertEqual(
            category_hubs.count(), 0, "No category hubs should exist in Hub model"
        )

    def test_no_duplicates_created(self):
        """Test that running the command multiple times doesn't create duplicates."""
        # Run the command twice
        call_command("seed_hub_categories")

        # Count items after first run
        hub_category_count = HubCategory.objects.count()
        subcategory_hub_count = Hub.objects.filter(namespace="subcategory").count()

        # Run again
        call_command("seed_hub_categories")

        # Counts should remain the same
        self.assertEqual(HubCategory.objects.count(), hub_category_count)
        self.assertEqual(
            Hub.objects.filter(namespace="subcategory").count(), subcategory_hub_count
        )

    def test_case_insensitive_duplicate_prevention(self):
        """Test that case variations don't create duplicates."""
        # Create a HubCategory with different case
        HubCategory.objects.create(category_name="computer science")

        # Run the seed command
        call_command("seed_hub_categories")

        # Check that no duplicates were created
        self.assertEqual(
            HubCategory.objects.filter(
                category_name__iexact="computer science"
            ).count(),
            1,
        )

    def test_all_categories_and_subcategories_exist(self):
        """Test that all categories/subcategories from master list exist."""
        # Run the seed command
        call_command("seed_hub_categories")

        master_categories = SeedCommand.get_master_categories()

        # Check all categories exist in HubCategory
        for category_name in master_categories.keys():
            self.assertTrue(
                HubCategory.objects.filter(
                    category_name__iexact=category_name
                ).exists(),
                f"HubCategory '{category_name}' should exist",
            )

        # Check all subcategories
        for category_name, subcategories in master_categories.items():
            for subcategory_name in subcategories:
                subcategory_hub = Hub.objects.filter(
                    name__iexact=subcategory_name, namespace="subcategory"
                ).first()
                self.assertIsNotNone(
                    subcategory_hub,
                    f"Subcategory hub '{subcategory_name}' should exist",
                )

                # Check that subcategory is linked to correct HubCategory
                hub_category = HubCategory.objects.filter(
                    category_name__iexact=category_name
                ).first()
                self.assertEqual(
                    subcategory_hub.category,
                    hub_category,
                    f"Subcategory '{subcategory_name}' should be linked to "
                    f"HubCategory '{category_name}'",
                )

    def test_hub_category_updates(self):
        """Test that existing hubs get their category field updated."""
        # Create a HubCategory
        bio_hub_cat = HubCategory.objects.create(category_name="Biology")

        # Create a subcategory hub without linking to HubCategory
        neuro_hub = Hub.objects.create(
            name="Neuroscience",
            namespace="subcategory",
            description="Neuroscience subcategory",
            # Note: not setting category field
        )

        # Run the seed command
        call_command("seed_hub_categories")

        # Refresh from database
        neuro_hub.refresh_from_db()

        # Check that subcategory hub now has correct category
        self.assertEqual(neuro_hub.category, bio_hub_cat)

    def test_dry_run_makes_no_changes(self):
        """Test that dry-run mode doesn't create anything."""
        # Get initial counts
        initial_hub_count = Hub.objects.count()
        initial_category_count = HubCategory.objects.count()

        # Run in dry-run mode
        call_command("seed_hub_categories", "--dry-run")

        # Counts should be unchanged
        self.assertEqual(Hub.objects.count(), initial_hub_count)
        self.assertEqual(HubCategory.objects.count(), initial_category_count)

    def test_subcategory_parent_relationships(self):
        """Test that subcategories are properly linked to their HubCategories."""
        # Run the seed command
        call_command("seed_hub_categories")

        # Test a specific subcategory relationship
        machine_learning = Hub.objects.get(
            name="Machine Learning", namespace="subcategory"
        )
        computer_science_cat = HubCategory.objects.get(category_name="Computer Science")

        self.assertEqual(
            machine_learning.category,
            computer_science_cat,
            "Machine Learning should be linked to Computer Science HubCategory",
        )

    def test_hub_categories_created_as_prerequisite(self):
        """Test that HubCategories are created before creating hubs."""
        # Start with no HubCategories
        self.assertEqual(HubCategory.objects.count(), 0)

        # Run the seed command
        call_command("seed_hub_categories")

        # Get master categories
        master_categories = SeedCommand.get_master_categories()

        # Verify all HubCategories were created
        self.assertEqual(
            HubCategory.objects.count(),
            len(master_categories),
            "All HubCategories should be created",
        )

        # Verify every Hub has a corresponding HubCategory
        for hub in Hub.objects.all():
            self.assertIsNotNone(
                hub.category, f"Hub '{hub.name}' should have a HubCategory"
            )
