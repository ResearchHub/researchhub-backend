"""
Management command to seed hubs from external preprint server mappings.
This creates hubs based on the mappings from arXiv, bioRxiv, ChemRxiv, and MedRxiv.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from hub.mappers.arxiv_mappings import ARXIV_MAPPINGS
from hub.mappers.biorxiv_mappings import BIORXIV_MAPPINGS
from hub.mappers.chemrxiv_mappings import CHEMRXIV_MAPPINGS
from hub.mappers.medrxiv_mappings import MEDRXIV_MAPPINGS
from hub.models import Hub


class Command(BaseCommand):
    help = "Seed hubs from external preprint server mappings"

    # Available mapping sources
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
            help="Show what would be created without making changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed output including lists of hubs",
        )
        parser.add_argument(
            "--source",
            choices=["arxiv", "biorxiv", "chemrxiv", "medrxiv", "all"],
            default="all",
            help="Which mapping source to process (default: all)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verbose = options["verbose"]
        source = options["source"]

        self.stdout.write(
            self.style.WARNING(
                f"{'DRY RUN: ' if dry_run else ''}"
                f"Processing external mappings ({source})..."
            )
        )

        # Get mappings based on source
        mappings_to_process = self._get_mappings(source)

        # Track what needs to be created
        hubs_to_create = []
        hubs_existing = []

        # Process all mappings
        for source_name, mappings in mappings_to_process.items():
            self.stdout.write(f"\nProcessing {source_name} mappings...")

            for external_category, hub_names in mappings.items():
                # Process all hub names in the mapping
                for hub_name in hub_names:
                    if hub_name:  # Skip None/empty values
                        self._process_hub(hub_name, hubs_to_create, hubs_existing)

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
        if source == "all":
            return self.MAPPINGS
        else:
            return {source: self.MAPPINGS[source]}

    def _process_hub(self, hub_name, to_create, existing):
        """Process a hub - check if it exists or needs to be created."""
        existing_hub = Hub.objects.filter(name__iexact=hub_name).first()

        if existing_hub:
            if existing_hub.name not in existing:
                existing.append(existing_hub.name)
        else:
            if hub_name not in to_create:
                to_create.append(hub_name)

    def _display_summary(self, hubs_to_create, hubs_existing, verbose):
        """Display a comprehensive summary of what will be created vs what exists."""
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 70)

        # Hubs summary
        self.stdout.write(f"\nHubs to create: {len(hubs_to_create)}")
        if verbose and hubs_to_create:
            for hub in hubs_to_create:
                self.stdout.write(f"  + {hub}")
        if hubs_to_create:
            self.stdout.write(f"List: {', '.join(hubs_to_create)}")

        self.stdout.write(f"\nHubs already exist: {len(hubs_existing)}")
        if verbose and hubs_existing:
            for hub in hubs_existing:
                self.stdout.write(f"  - {hub}")
        if hubs_existing:
            self.stdout.write(f"List: {', '.join(hubs_existing)}")

        # Total summary
        self.stdout.write(f"\nTOTAL to create: {len(hubs_to_create)}")
        self.stdout.write(f"TOTAL already exist: {len(hubs_existing)}")
        self.stdout.write("=" * 70 + "\n")

    def _create_hubs(self, hubs_to_create, verbose):
        """Create the actual hubs."""
        if not hubs_to_create:
            self.stdout.write(
                self.style.SUCCESS("No new hubs need to be created. All already exist.")
            )
            return

        try:
            with transaction.atomic():
                created_hubs = 0
                for hub_name in hubs_to_create:
                    Hub.objects.create(
                        name=hub_name,
                        description=f"{hub_name} - research hub",
                    )
                    created_hubs += 1
                    if verbose:
                        self.stdout.write(
                            self.style.SUCCESS(f"Created hub: {hub_name}")
                        )

                self.stdout.write(
                    self.style.SUCCESS(f"\nSuccessfully created {created_hubs} hubs")
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during creation: {str(e)}"))
            raise
