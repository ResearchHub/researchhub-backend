from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):
    help = "Check where paper PDFs are stored and show file locations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--paper_id",
            type=int,
            help="Check file location for a specific paper ID",
        )

    def handle(self, *args, **options):
        paper_id = options.get("paper_id")

        # Show storage configuration
        self.stdout.write("\n=== Storage Configuration ===")
        self.stdout.write(f"Storage Backend: {settings.STORAGES['default']['BACKEND']}")

        if hasattr(default_storage, "location"):
            self.stdout.write(f"Local Storage Location: {default_storage.location}")
        else:
            self.stdout.write("Using cloud storage (S3)")
            if hasattr(settings, "AWS_STORAGE_BUCKET_NAME"):
                self.stdout.write(f"S3 Bucket: {settings.AWS_STORAGE_BUCKET_NAME}")
            if hasattr(settings, "AWS_S3_CUSTOM_DOMAIN"):
                self.stdout.write(f"S3 Domain: {settings.AWS_S3_CUSTOM_DOMAIN}")

        if paper_id:
            # Check specific paper
            try:
                paper = Paper.objects.get(id=paper_id)
                self.stdout.write(f"\n=== Paper {paper_id} ===")
                self.stdout.write(f"Title: {paper.title}")
                self.stdout.write(f"PDF URL: {paper.pdf_url or paper.url}")

                if paper.file:
                    self.stdout.write(f"\nFile Information:")
                    self.stdout.write(f"  Relative path: {paper.file.name}")
                    self.stdout.write(f"  File URL: {paper.file.url}")

                    try:
                        full_path = paper.file.path
                        self.stdout.write(f"  Full path: {full_path}")
                        import os

                        if os.path.exists(full_path):
                            size = os.path.getsize(full_path)
                            self.stdout.write(f"  File exists: Yes ({size:,} bytes)")
                        else:
                            self.stdout.write(f"  File exists: No (may be in S3)")
                    except NotImplementedError:
                        self.stdout.write(f"  Full path: N/A (using cloud storage)")
                else:
                    self.stdout.write("\nNo file attached to this paper")

            except Paper.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Paper {paper_id} not found"))
        else:
            # Show statistics
            total_papers = Paper.objects.count()
            papers_with_files = (
                Paper.objects.exclude(file__isnull=True).exclude(file="").count()
            )

            self.stdout.write(f"\n=== Statistics ===")
            self.stdout.write(f"Total papers: {total_papers}")
            self.stdout.write(f"Papers with PDFs: {papers_with_files}")
            self.stdout.write(
                f"Papers without PDFs: {total_papers - papers_with_files}"
            )
