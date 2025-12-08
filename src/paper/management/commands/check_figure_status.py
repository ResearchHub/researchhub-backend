"""
Management command to check figure extraction status for papers.
"""

from django.core.management.base import BaseCommand

from paper.models import Figure, Paper


class Command(BaseCommand):
    help = "Check figure extraction status for papers"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            nargs="?",
            help="Specific paper ID to check (optional)",
        )
        parser.add_argument(
            "--summary",
            action="store_true",
            help="Show summary statistics",
        )

    def handle(self, *args, **options):
        if options["paper_id"]:
            self._check_single_paper(options["paper_id"])
        elif options["summary"]:
            self._show_summary()
        else:
            self.stdout.write(
                self.style.ERROR(
                    "Please provide a paper_id or use --summary for overall stats"
                )
            )

    def _check_single_paper(self, paper_id):
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Paper {paper_id} does not exist"))
            return

        figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE)
        primary = Figure.objects.filter(paper=paper, is_primary=True).first()
        previews = Figure.objects.filter(paper=paper, figure_type=Figure.PREVIEW)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Paper ID: {paper.id}")
        self.stdout.write(f"Title: {paper.title}")
        self.stdout.write(f"PDF File: {paper.file.name if paper.file else 'None'}")
        self.stdout.write("-" * 60)
        self.stdout.write(f"Extracted Figures: {figures.count()}")
        self.stdout.write(f"Preview Figures: {previews.count()}")
        if primary:
            primary_type = (
                "preview" if primary.figure_type == Figure.PREVIEW else "figure"
            )
            self.stdout.write(
                f"Primary {primary_type}: {primary.file.name} "
                f"[{primary.figure_type}]"
            )
        else:
            self.stdout.write("Primary Figure: None")
        self.stdout.write("=" * 60)

        if figures.exists():
            self.stdout.write("\nExtracted Figures:")
            for idx, fig in enumerate(figures, 1):
                primary_marker = " [PRIMARY]" if fig.is_primary else ""
                self.stdout.write(
                    f"  {idx}. {fig.file.name}{primary_marker} "
                    f"({fig.file.size} bytes)"
                )

    def _show_summary(self):
        total_papers = Paper.objects.count()
        papers_with_pdf = Paper.objects.filter(file__isnull=False).count()
        papers_with_figures = (
            Paper.objects.filter(figures__figure_type=Figure.FIGURE).distinct().count()
        )
        papers_with_primary = (
            Paper.objects.filter(figures__is_primary=True).distinct().count()
        )

        total_figures = Figure.objects.filter(figure_type=Figure.FIGURE).count()
        total_previews = Figure.objects.filter(figure_type=Figure.PREVIEW).count()
        total_primary = Figure.objects.filter(is_primary=True).count()

        papers_needing_extraction = (
            Paper.objects.filter(file__isnull=False)
            .exclude(figures__figure_type=Figure.FIGURE)
            .distinct()
            .count()
        )

        papers_needing_selection = (
            Paper.objects.filter(figures__figure_type=Figure.FIGURE)
            .exclude(figures__is_primary=True)
            .distinct()
            .count()
        )

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("FIGURE EXTRACTION STATUS SUMMARY")
        self.stdout.write("=" * 60)
        self.stdout.write("\nPapers:")
        self.stdout.write(f"  Total papers: {total_papers:,}")
        self.stdout.write(f"  Papers with PDFs: {papers_with_pdf:,}")
        self.stdout.write(f"  Papers with extracted figures: {papers_with_figures:,}")
        self.stdout.write(f"  Papers with primary images: {papers_with_primary:,}")
        self.stdout.write("\nFigures:")
        self.stdout.write(f"  Total extracted figures: {total_figures:,}")
        self.stdout.write(f"  Total previews: {total_previews:,}")
        self.stdout.write(f"  Primary images (any type): {total_primary:,}")
        self.stdout.write("\nPending:")
        self.stdout.write(f"  Papers needing extraction: {papers_needing_extraction:,}")
        self.stdout.write(
            f"  Papers needing primary selection: {papers_needing_selection:,}"
        )
        self.stdout.write("=" * 60)
