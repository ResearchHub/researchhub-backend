"""
Management command to seed Hub objects from external mappings.

This command processes mappings from various preprint servers (arXiv, bioRxiv,
MedRxiv, ChemRxiv) and creates Hub objects for each unique hub in the mappings
if they don't already exist.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from hub.mappers.arxiv_mappings import ARXIV_MAPPINGS
from hub.mappers.biorxiv_mappings import BIORXIV_MAPPINGS
from hub.mappers.chemrxiv_mappings import CHEMRXIV_MAPPINGS
from hub.mappers.medrxiv_mappings import MEDRXIV_MAPPINGS
from hub.models import Hub


class Command(BaseCommand):
    help = "Seeds Hub objects based on external preprint server mappings"

    # The mappings now contain slugs
    MAPPINGS = {
        "arxiv": ARXIV_MAPPINGS,
        "biorxiv": BIORXIV_MAPPINGS,
        "chemrxiv": CHEMRXIV_MAPPINGS,
        "medrxiv": MEDRXIV_MAPPINGS,
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without actually creating anything",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed output including individual hub names",
        )
        parser.add_argument(
            "--source",
            type=str,
            choices=["all", "arxiv", "biorxiv", "medrxiv", "chemrxiv"],
            default="all",
            help="Which mapping source to process (default: all)",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        verbose = options.get("verbose", False)
        source = options.get("source", "all")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Processing external mappings ({source})..."
                )
            )
        else:
            self.stdout.write(f"Processing external mappings ({source})...")

        # Get mappings based on source
        mappings_to_process = self._get_mappings(source)

        # Track what needs to be created
        hubs_to_create = []
        hubs_existing = []

        # Process all mappings
        for source_name, mappings in mappings_to_process.items():
            self.stdout.write(f"\nProcessing {source_name} mappings...")

            for external_category, hub_slugs in mappings.items():
                # Process all hub slugs in the mapping
                for hub_slug in hub_slugs:
                    if hub_slug:  # Skip None/empty values
                        self._process_hub(hub_slug, hubs_to_create, hubs_existing)

        # Remove duplicates while preserving order
        hubs_to_create = list(dict.fromkeys(hubs_to_create))
        hubs_existing = list(dict.fromkeys(hubs_existing))

        # Display summary
        self._display_summary(hubs_to_create, hubs_existing, verbose)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN completed. No changes were made.")
            )
            return

        # Perform the actual creation
        self._create_hubs(hubs_to_create, verbose)

    def _get_mappings(self, source):
        """Get the mappings based on the source parameter."""
        return self.MAPPINGS if source == "all" else {source: self.MAPPINGS[source]}

    def _process_hub(self, hub_slug, to_create, existing):
        """Process a hub - check if it exists or needs to be created."""
        # Check if a hub with this slug already exists
        existing_hub = Hub.objects.filter(slug=hub_slug).first()

        if existing_hub:
            if hub_slug not in existing:
                existing.append(hub_slug)
        else:
            if hub_slug not in to_create:
                to_create.append(hub_slug)

    def _display_summary(self, hubs_to_create, hubs_existing, verbose):
        """Display a comprehensive summary of what will be created vs what exists."""
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 70)

        # Hubs summary (display slugs)
        self.stdout.write(f"\nHubs to create: {len(hubs_to_create)}")
        if verbose and hubs_to_create:
            for hub_slug in hubs_to_create:
                self.stdout.write(f"  + {hub_slug}")
        if hubs_to_create:
            self.stdout.write(f"List: {', '.join(hubs_to_create)}")

        self.stdout.write(f"\nHubs already exist: {len(hubs_existing)}")
        if verbose and hubs_existing:
            for hub_slug in hubs_existing:
                # Get the actual hub to show its name
                hub = Hub.objects.filter(slug=hub_slug).first()
                if hub:
                    self.stdout.write(f"  - {hub_slug} ({hub.name})")
                else:
                    self.stdout.write(f"  - {hub_slug}")
        if hubs_existing:
            # For existing hubs, show their actual names in the list
            existing_names = []
            for slug in hubs_existing:
                hub = Hub.objects.filter(slug=slug).first()
                if hub:
                    existing_names.append(hub.name)
                else:
                    existing_names.append(slug)  # Fallback to slug if hub not found
            self.stdout.write(f"List: {', '.join(existing_names)}")

        # Total summary
        self.stdout.write(f"\nTOTAL to create: {len(hubs_to_create)}")
        self.stdout.write(f"TOTAL already exist: {len(hubs_existing)}")
        self.stdout.write("=" * 70)

    def _create_hubs(self, hubs_to_create, verbose):
        """Create the actual hubs using slugs."""
        if not hubs_to_create:
            self.stdout.write(
                self.style.SUCCESS("No new hubs need to be created. All already exist.")
            )
            return

        try:
            with transaction.atomic():
                created_hubs = 0
                for hub_slug in hubs_to_create:
                    # Create name from slug
                    hub_name = self._slug_to_display_name(hub_slug)

                    # Create hub with explicit slug
                    Hub.objects.create(
                        name=hub_name,
                        slug=hub_slug,
                        description=f"{hub_name} - research hub",
                    )
                    created_hubs += 1
                    if verbose:
                        self.stdout.write(
                            self.style.SUCCESS(f"Created hub: {hub_slug} ({hub_name})")
                        )

                self.stdout.write(
                    self.style.SUCCESS(f"\nSuccessfully created {created_hubs} hubs")
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during creation: {str(e)}"))
            raise

    def _slug_to_display_name(self, slug):
        """Convert a slug to a display name for hub creation."""
        # Handle special cases where simple title case doesn't work
        special_cases = {
            "k-theory": "K-Theory",
            "c-h-activation": "C-H Activation",
            "hiv-aids": "HIV/AIDS",
        }

        if slug in special_cases:
            return special_cases[slug]

        # General conversion: replace hyphens with spaces and title case
        return slug.replace("-", " ").title()
