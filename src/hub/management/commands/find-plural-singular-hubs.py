"""
Find potential plural/singular duplicate hubs (e.g., "Cell" vs "Cells").
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from hub.models import Hub


class Command(BaseCommand):
    help = (
        "Identify potential plural/singular duplicate hubs "
        "to help clean up low-quality variations"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--namespace",
            type=str,
            help="Filter by namespace (e.g., 'journal')",
        )
        parser.add_argument(
            "--exclude-removed",
            action="store_true",
            help="Exclude hubs already marked as removed",
        )
        parser.add_argument(
            "--min-pair-size",
            type=int,
            default=2,
            help="Minimum number of hubs in a group to report (default: 2)",
        )
        parser.add_argument(
            "--output-file",
            type=str,
            help="Save results to a file",
        )

    def handle(self, *args, **options):
        namespace = options.get("namespace")
        exclude_removed = options.get("exclude_removed", False)
        min_pair_size = options.get("min_pair_size", 2)
        output_file = options.get("output_file")

        self.stdout.write(self.style.SUCCESS("Finding plural/singular hub pairs...\n"))

        # Build queryset
        queryset = Hub.objects.all()
        if namespace:
            queryset = queryset.filter(namespace=namespace)
            self.stdout.write(f"Filtering by namespace: {namespace}")
        if exclude_removed:
            queryset = queryset.filter(is_removed=False)
            self.stdout.write("Excluding already removed hubs")

        self.stdout.write(f"Total hubs to analyze: {queryset.count()}\n")

        # Group hubs by potential root forms
        pairs = self._find_pairs(queryset, min_pair_size)

        if output_file:
            self._save_to_file(pairs, output_file)
        else:
            self._display_results(pairs)

    def _find_pairs(self, queryset, min_pair_size):
        """
        Find potential plural/singular pairs.

        Returns a list of tuples: (root_form, [hub1, hub2, ...])
        """
        names_by_root = defaultdict(list)

        for hub in queryset.order_by("id"):
            name_lower = hub.name.lower().strip()

            # Generate potential root forms
            roots = self._generate_root_forms(name_lower)

            # Add to all possible roots
            for root in roots:
                names_by_root[root].append(hub)

        # Filter to only groups with multiple hubs
        pairs = []
        for root, hubs in names_by_root.items():
            if len(hubs) >= min_pair_size:
                # Check if they're actually different names (not exact duplicates)
                unique_names = set(h.name.lower() for h in hubs)
                if len(unique_names) > 1:
                    pairs.append((root, hubs))

        # Sort by number of hubs in group (largest first)
        pairs.sort(key=lambda x: len(x[1]), reverse=True)

        return pairs

    def _generate_root_forms(self, name):
        """
        Generate potential root forms for a name.

        Returns a set of possible root forms.
        """
        roots = set()

        # Add the name itself
        roots.add(name)

        # Pattern 1: Simple 's' removal (cells -> cell)
        if name.endswith("s") and len(name) > 2 and not name.endswith("ss"):
            roots.add(name[:-1])

        # Pattern 2: 'es' removal (boxes -> box, classes -> class)
        if name.endswith("es") and len(name) > 3:
            roots.add(name[:-2])
            # Try removing just 's' too (genes -> gene)
            roots.add(name[:-1])

        # Pattern 3: 'ies' -> 'y' (studies -> study, categories -> category)
        if name.endswith("ies") and len(name) > 4:
            roots.add(name[:-3] + "y")

        # Pattern 4: 'ves' -> 'f' or 'fe' (lives -> life, wolves -> wolf)
        if name.endswith("ves") and len(name) > 4:
            roots.add(name[:-3] + "f")
            roots.add(name[:-3] + "fe")

        # Pattern 5: 'i' -> 'us' (fungi -> fungus, nuclei -> nucleus)
        if name.endswith("i") and len(name) > 2:
            roots.add(name[:-1] + "us")

        # Pattern 6: 'a' -> 'um' (criteria -> criterion, bacteria -> bacterium)
        if name.endswith("a") and len(name) > 2:
            roots.add(name[:-1] + "um")

        # Pattern 7: 'ae' -> 'a' (formulae -> formula)
        if name.endswith("ae") and len(name) > 3:
            roots.add(name[:-1])

        return roots

    def _display_results(self, pairs):
        """Display results to stdout"""
        self.stdout.write("=" * 80)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nFound {len(pairs)} potential plural/singular groups\n"
            )
        )

        if not pairs:
            self.stdout.write(self.style.SUCCESS("No plural/singular pairs found!"))
            return

        for root, hubs in pairs:
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(
                self.style.WARNING(
                    f'\nPotential Group (root: "{root}") - {len(hubs)} hubs:\n'
                )
            )

            # Sort by paper count (descending) to show most active first
            hubs_sorted = sorted(
                hubs, key=lambda h: (h.paper_count, h.subscriber_count), reverse=True
            )

            for hub in hubs_sorted:
                self.stdout.write(f"  Name: {hub.name}")
                self.stdout.write(f"    ID: {hub.id}")
                self.stdout.write(f"    Slug: {hub.slug}")
                self.stdout.write(f"    Namespace: {hub.namespace or 'None'}")
                self.stdout.write(f"    Paper Count: {hub.paper_count}")
                self.stdout.write(f"    Subscriber Count: {hub.subscriber_count}")
                self.stdout.write(f"    Documents: {hub.related_documents.count()}")

                # Suggest which one to keep
                if hub == hubs_sorted[0]:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "    >>> RECOMMENDED TO KEEP " "(highest activity)"
                        )
                    )
                self.stdout.write("")

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("\n📊 Summary:\n"))
        self.stdout.write(f"  Total groups found: {len(pairs)}")

        # Calculate potential hubs to remove (all except the primary in each group)
        potential_removals = sum(len(hubs) - 1 for _, hubs in pairs)
        self.stdout.write(f"  Potential hubs to review/remove: {potential_removals}")

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.WARNING(
                "\n💡 Review each group manually to decide which to keep/remove"
            )
        )

    def _save_to_file(self, pairs, filepath):
        """Save results to a file"""
        with open(filepath, "w") as f:
            f.write("# Potential Plural/Singular Hub Pairs\n")
            f.write(f"# Generated: {self._get_timestamp()}\n")
            f.write(f"# Total groups: {len(pairs)}\n")
            f.write("\n")

            for root, hubs in pairs:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"Potential Group (root: '{root}') - {len(hubs)} hubs\n")
                f.write(f"{'=' * 80}\n\n")

                # Sort by paper count
                hubs_sorted = sorted(
                    hubs,
                    key=lambda h: (h.paper_count, h.subscriber_count),
                    reverse=True,
                )

                for hub in hubs_sorted:
                    f.write(f"Name: {hub.name}\n")
                    f.write(f"  ID: {hub.id}\n")
                    f.write(f"  Slug: {hub.slug}\n")
                    f.write(f"  Namespace: {hub.namespace or 'None'}\n")
                    f.write(f"  Paper Count: {hub.paper_count}\n")
                    f.write(f"  Subscriber Count: {hub.subscriber_count}\n")
                    f.write(f"  Documents: {hub.related_documents.count()}\n")

                    if hub == hubs_sorted[0]:
                        f.write("  >>> RECOMMENDED TO KEEP (highest activity)\n")
                    f.write("\n")

            # Hub IDs for potential removal
            f.write("\n" + "=" * 80 + "\n")
            f.write("# Hub IDs to review (excluding recommended keepers)\n")
            f.write(f"{'=' * 80}\n\n")

            for root, hubs in pairs:
                hubs_sorted = sorted(
                    hubs,
                    key=lambda h: (h.paper_count, h.subscriber_count),
                    reverse=True,
                )
                # Skip the first one (recommended keeper)
                for hub in hubs_sorted[1:]:
                    f.write(f"{hub.id}  # {hub.name} (vs {hubs_sorted[0].name})\n")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Analysis saved to {filepath}\n"
                f"  Found {len(pairs)} potential plural/singular groups"
            )
        )

    def _get_timestamp(self):
        """Get current timestamp for file headers"""
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
