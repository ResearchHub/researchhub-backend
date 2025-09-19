"""
Tests for the seed_hubs_from_mappings management command.
"""

from django.core.management import call_command
from django.test import TestCase

from hub.models import Hub


class SeedHubsFromMappingsTestCase(TestCase):
    """Test the seed_hubs_from_mappings management command."""

    def setUp(self):
        """Set up test environment."""
        # Clear any existing hubs
        Hub.objects.all().delete()

    def test_hubs_created_from_mappings(self):
        """Test that hubs are created from external mappings."""
        # Run the seed command for a specific source to limit test scope
        call_command("seed_hubs_from_mappings", "--source", "biorxiv")

        # Check that some expected hubs exist
        expected_hubs = ["Biology", "Neuroscience", "Biochemistry", "Medicine"]
        for hub_name in expected_hubs:
            hub = Hub.objects.filter(name__iexact=hub_name).first()
            self.assertIsNotNone(hub, f"Hub '{hub_name}' should exist")

    def test_no_duplicates_created(self):
        """Test that running the command multiple times doesn't create duplicates."""
        # Run the command twice
        call_command("seed_hubs_from_mappings", "--source", "biorxiv")

        # Count hubs after first run
        hub_count = Hub.objects.count()

        # Run again
        call_command("seed_hubs_from_mappings", "--source", "biorxiv")

        # Count should remain the same
        self.assertEqual(
            Hub.objects.count(), hub_count, "No duplicate hubs should be created"
        )

    def test_case_insensitive_duplicate_prevention(self):
        """Test that case variations don't create duplicates."""
        # Create hubs with different cases
        Hub.objects.create(name="BIOLOGY", description="All caps biology")
        Hub.objects.create(name="neuroscience", description="Lowercase neuroscience")
        Hub.objects.create(name="BiOcHeMiStRy", description="Mixed case biochemistry")

        # Run the seed command
        call_command("seed_hubs_from_mappings", "--source", "biorxiv")

        # Check that no duplicates were created
        self.assertEqual(
            Hub.objects.filter(name__iexact="biology").count(),
            1,
            "Only one Biology hub should exist",
        )
        self.assertEqual(
            Hub.objects.filter(name__iexact="neuroscience").count(),
            1,
            "Only one Neuroscience hub should exist",
        )
        self.assertEqual(
            Hub.objects.filter(name__iexact="biochemistry").count(),
            1,
            "Only one Biochemistry hub should exist",
        )

    def test_case_preserved_for_existing_hubs(self):
        """Test that existing hub names preserve their original casing."""
        # Create a hub with specific casing
        original_hub = Hub.objects.create(
            name="NeuroScience", description="Original casing"
        )

        # Run the seed command
        call_command("seed_hubs_from_mappings", "--source", "biorxiv")

        # Check that the original casing is preserved
        hub = Hub.objects.get(id=original_hub.id)
        self.assertEqual(
            hub.name, "NeuroScience", "Original hub name casing should be preserved"
        )

    def test_dry_run_makes_no_changes(self):
        """Test that dry-run mode doesn't create anything."""
        # Get initial count
        initial_hub_count = Hub.objects.count()

        # Run in dry-run mode
        call_command("seed_hubs_from_mappings", "--dry-run")

        # Count should be unchanged
        self.assertEqual(
            Hub.objects.count(), initial_hub_count, "Dry-run should not create any hubs"
        )

    def test_all_hub_names_from_mapping_exist(self):
        """Test that all hub names from a mapping are processed."""
        # Use a smaller source for testing
        from hub.mappers.medrxiv_mappings import MEDRXIV_MAPPINGS

        # Run the seed command
        call_command("seed_hubs_from_mappings", "--source", "medrxiv")

        # Collect all unique hub slugs from the mappings
        expected_hub_slugs = set()
        for first_slug, second_slug in MEDRXIV_MAPPINGS.values():
            if first_slug:
                expected_hub_slugs.add(first_slug)
            if second_slug:
                expected_hub_slugs.add(second_slug)

        # Check that all expected hubs exist by slug
        for hub_slug in expected_hub_slugs:
            exists = Hub.objects.filter(slug=hub_slug).exists()
            self.assertTrue(
                exists, f"Hub with slug '{hub_slug}' from MedRxiv mappings should exist"
            )

    def test_specific_source_only_creates_its_hubs(self):
        """Test that specifying a source only creates hubs from that source."""
        # Run for bioRxiv only
        call_command("seed_hubs_from_mappings", "--source", "biorxiv")

        # Check that bioRxiv-specific hubs exist
        self.assertTrue(
            Hub.objects.filter(name__iexact="Zoology").exists(),
            "Zoology (from bioRxiv) should exist",
        )

        # Check that arXiv-only hubs don't exist
        self.assertFalse(
            Hub.objects.filter(name__iexact="Quantum Computing").exists(),
            "Quantum Computing (arXiv-only) should not exist",
        )
