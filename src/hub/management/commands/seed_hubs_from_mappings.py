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

        # Track what needs to be created, updated, or already exists
        hubs_to_create = {}  # {slug: namespace}
        hubs_to_update = {}  # {slug: namespace}
        hubs_existing = {}  # {slug: namespace}

        # Process all mappings
        for source_name, mappings in mappings_to_process.items():
            self.stdout.write(f"\nProcessing {source_name} mappings...")

            for external_category, hub_slugs in mappings.items():
                # Process all hub slugs in the mapping with position-based namespace
                for position, hub_slug in enumerate(hub_slugs):
                    if hub_slug:  # Skip None/empty values
                        # Position 0 = category, position 1+ = subcategory
                        namespace = "category" if position == 0 else "subcategory"
                        self._process_hub(
                            hub_slug,
                            namespace,
                            hubs_to_create,
                            hubs_to_update,
                            hubs_existing,
                        )

        # Display summary
        self._display_summary(hubs_to_create, hubs_to_update, hubs_existing, verbose)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN completed. No changes were made.")
            )
            return

        # Perform the actual creation and updates
        self._create_and_update_hubs(hubs_to_create, hubs_to_update, verbose)

    def _get_mappings(self, source):
        """Get the mappings based on the source parameter."""
        return self.MAPPINGS if source == "all" else {source: self.MAPPINGS[source]}

    def _process_hub(self, hub_slug, namespace, to_create, to_update, existing):
        """Process a hub - check if it exists, needs to be created, or updated."""
        # Check if a hub with this slug already exists
        existing_hub = Hub.objects.filter(slug=hub_slug).first()

        if existing_hub:
            # Hub exists - check if namespace needs updating
            if existing_hub.namespace != namespace:
                # Needs update
                if hub_slug not in to_update:
                    to_update[hub_slug] = namespace
            else:
                # Already correct
                if hub_slug not in existing:
                    existing[hub_slug] = namespace
        else:
            # Doesn't exist - needs creation
            if hub_slug not in to_create:
                to_create[hub_slug] = namespace

    def _display_summary(self, hubs_to_create, hubs_to_update, hubs_existing, verbose):
        """Display a summary of what will be created, updated, or already correct."""
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 70)

        # Hubs to create
        self.stdout.write(f"\nHubs to create: {len(hubs_to_create)}")
        if verbose and hubs_to_create:
            for hub_slug, namespace in hubs_to_create.items():
                self.stdout.write(f"  + {hub_slug} (namespace: {namespace})")
        if hubs_to_create:
            self.stdout.write(f"List: {', '.join(hubs_to_create.keys())}")

        # Hubs to update
        self.stdout.write(f"\nHubs to update: {len(hubs_to_update)}")
        if verbose and hubs_to_update:
            for hub_slug, namespace in hubs_to_update.items():
                hub = Hub.objects.filter(slug=hub_slug).first()
                old_namespace = hub.namespace if hub else "None"
                self.stdout.write(f"  * {hub_slug} ({old_namespace} → {namespace})")
        if hubs_to_update:
            self.stdout.write(f"List: {', '.join(hubs_to_update.keys())}")

        # Hubs already correct
        self.stdout.write(f"\nHubs already correct: {len(hubs_existing)}")
        if verbose and hubs_existing:
            for hub_slug, namespace in hubs_existing.items():
                hub = Hub.objects.filter(slug=hub_slug).first()
                if hub:
                    self.stdout.write(
                        f"  - {hub_slug} ({hub.name}, namespace: {namespace})"
                    )
                else:
                    self.stdout.write(f"  - {hub_slug} (namespace: {namespace})")
        if hubs_existing:
            # For existing hubs, show their actual names in the list
            existing_names = []
            for slug in hubs_existing.keys():
                hub = Hub.objects.filter(slug=slug).first()
                if hub:
                    existing_names.append(hub.name)
                else:
                    existing_names.append(slug)
            self.stdout.write(f"List: {', '.join(existing_names)}")

        # Total summary
        self.stdout.write(f"\nTOTAL to create: {len(hubs_to_create)}")
        self.stdout.write(f"TOTAL to update: {len(hubs_to_update)}")
        self.stdout.write(f"TOTAL already correct: {len(hubs_existing)}")
        self.stdout.write("=" * 70)

    def _create_and_update_hubs(self, hubs_to_create, hubs_to_update, verbose):
        """Create new hubs and update existing hubs with namespace."""
        if not hubs_to_create and not hubs_to_update:
            self.stdout.write(
                self.style.SUCCESS(
                    "No hubs need to be created or updated. All already correct."
                )
            )
            return

        try:
            with transaction.atomic():
                # Create new hubs
                created_hubs = 0
                for hub_slug, namespace in hubs_to_create.items():
                    # Create name from slug
                    hub_name = self._slug_to_display_name(hub_slug)

                    # Create hub with explicit slug and namespace
                    Hub.objects.create(
                        name=hub_name,
                        slug=hub_slug,
                        description=f"{hub_name} - research hub",
                        namespace=namespace,
                    )
                    created_hubs += 1
                    if verbose:
                        msg = f"Created hub: {hub_slug} ({hub_name}, "
                        msg += f"namespace: {namespace})"
                        self.stdout.write(self.style.SUCCESS(msg))

                # Update existing hubs
                updated_hubs = 0
                for hub_slug, namespace in hubs_to_update.items():
                    hub = Hub.objects.filter(slug=hub_slug).first()
                    if hub:
                        old_namespace = hub.namespace
                        hub.namespace = namespace
                        hub.save(update_fields=["namespace"])
                        updated_hubs += 1
                        if verbose:
                            msg = f"Updated hub: {hub_slug} ({hub.name}, "
                            msg += f"{old_namespace} → {namespace})"
                            self.stdout.write(self.style.SUCCESS(msg))

                # Summary
                if created_hubs > 0:
                    msg = f"\nSuccessfully created {created_hubs} hubs"
                    self.stdout.write(self.style.SUCCESS(msg))
                if updated_hubs > 0:
                    msg = f"Successfully updated {updated_hubs} hubs"
                    self.stdout.write(self.style.SUCCESS(msg))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during operation: {str(e)}"))
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
