"""
Management command to test figure extraction for a paper.
"""

from django.core.management.base import BaseCommand, CommandError

from paper.models import Figure, Paper
from paper.tasks import extract_pdf_figures, select_primary_image


class Command(BaseCommand):
    help = "Test figure extraction and primary image selection for a paper"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            help="Paper ID to test",
        )
        parser.add_argument(
            "--skip-extraction",
            action="store_true",
            help="Skip extraction, only test primary selection",
        )
        parser.add_argument(
            "--skip-selection",
            action="store_true",
            help="Skip primary selection, only test extraction",
        )

    def handle(self, *args, **options):
        paper_id = options["paper_id"]

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} does not exist")

        self.stdout.write(f"\nTesting figure extraction for paper:")
        self.stdout.write(f"  ID: {paper.id}")
        self.stdout.write(f"  Title: {paper.title}")
        self.stdout.write(f"  PDF File: {paper.file.name if paper.file else 'None'}\n")

        # Step 1: Extract figures
        if not options["skip_extraction"]:
            self.stdout.write("Step 1: Extracting figures from PDF...")
            if not paper.file:
                self.stdout.write(
                    self.style.ERROR("  ERROR: Paper has no PDF file")
                )
                return

            result = extract_pdf_figures(paper.id)
            if result:
                figures = Figure.objects.filter(
                    paper=paper, figure_type=Figure.FIGURE
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Successfully extracted {figures.count()} figures"
                    )
                )
                for fig in figures:
                    self.stdout.write(f"    - {fig.file.name} ({fig.file.size} bytes)")
            else:
                self.stdout.write(self.style.ERROR("  ✗ Extraction failed"))
                return
        else:
            self.stdout.write("Step 1: Skipping extraction (--skip-extraction)")

        # Step 2: Select primary image
        if not options["skip_selection"]:
            self.stdout.write("\nStep 2: Selecting primary image using Bedrock...")
            figures = Figure.objects.filter(
                paper=paper, figure_type=Figure.FIGURE
            )
            if not figures.exists():
                self.stdout.write(
                    self.style.WARNING("  WARNING: No figures found, skipping selection")
                )
                return

            result = select_primary_image(paper.id)
            if result:
                primary = Figure.objects.filter(
                    paper=paper, figure_type=Figure.FIGURE, is_primary=True
                ).first()
                if primary:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  ✓ Selected primary image: {primary.file.name}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING("  ⚠ Selection completed but no primary set")
                    )
            else:
                self.stdout.write(
                    self.style.ERROR("  ✗ Primary selection failed")
                )
        else:
            self.stdout.write("Step 2: Skipping selection (--skip-selection)")

        # Summary
        self.stdout.write("\n" + "=" * 60)
        figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE)
        primary = figures.filter(is_primary=True).first()

        self.stdout.write("Summary:")
        self.stdout.write(f"  Total figures: {figures.count()}")
        self.stdout.write(
            f"  Primary figure: {primary.file.name if primary else 'None'}"
        )
        self.stdout.write("=" * 60)

