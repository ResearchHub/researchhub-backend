"""
Management command to generate abstract_fast_vector embeddings for papers
and update them in OpenSearch using sentence-transformers.

Usage:
    python manage.py generate_abstract_vectors --days 30
    python manage.py generate_abstract_vectors --days 7 --batch-size 50
    python manage.py generate_abstract_vectors --paper-ids 123,456,789
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, QuerySet
from django.utils import timezone

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    raise ImportError(
        "sentence-transformers is required. Install it with: pip install sentence-transformers"
    )

from paper.models import Paper
from search.documents.paper import PaperDocument
from utils.sentry import log_error

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Generate abstract_fast_vector embeddings for papers and update them in OpenSearch. "
        "You can specify how far back in time to generate vectors for using --days option."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            help="Number of days back from today to generate vectors for (e.g., 30 for last 30 days)",
        )
        parser.add_argument(
            "--paper-ids",
            type=str,
            help="Comma-separated list of paper IDs to generate vectors for (e.g., '123,456,789')",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Number of papers to process in each batch (default: 50)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without actually updating OpenSearch (for testing)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default="all-MiniLM-L6-v2",
            help="Sentence transformer model to use (default: all-MiniLM-L6-v2). "
            "Other fast options: all-mpnet-base-v2, paraphrase-MiniLM-L6-v2",
        )
        parser.add_argument(
            "--index-name",
            type=str,
            help="OpenSearch index name (default: uses PaperDocument index or 'paper_knn' if exists)",
        )
        parser.add_argument(
            "--device",
            type=str,
            default="cpu",
            help="Device to use for inference: 'cpu' or 'cuda' (default: cpu)",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip papers that already have abstract_fast_vector populated in OpenSearch",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit the number of papers to process (e.g., 1000 for first 1000 papers)",
        )

    def handle(self, *args, **options):
        days = options.get("days")
        paper_ids_str = options.get("paper_ids")
        batch_size = options.get("batch_size", 50)
        dry_run = options.get("dry_run", False)
        skip_existing = options.get("skip_existing", False)
        model_name = options.get("model", "all-MiniLM-L6-v2")
        device = options.get("device", "cpu")
        index_name = options.get("index_name")
        limit = options.get("limit")

        # Initialize sentence transformer model
        self.stdout.write(f"Loading sentence transformer model: {model_name}...")
        try:
            model = SentenceTransformer(model_name, device=device)
            self.stdout.write(
                self.style.SUCCESS(f"Model loaded successfully on {device}")
            )
        except Exception as e:
            raise CommandError(f"Failed to load model {model_name}: {str(e)}")

        self.model = model

        # Get OpenSearch client
        document = PaperDocument()
        client = document._index._get_connection()

        # Determine which index to use
        if not index_name:
            # Try paper_knn first, fall back to paper
            try:
                client.indices.get(index="paper_knn")
                index_name = "paper_knn"
                self.stdout.write(self.style.SUCCESS(f"Using index: {index_name}"))
            except Exception:
                index_name = PaperDocument._index._name
                self.stdout.write(
                    self.style.WARNING(
                        f"paper_knn index not found, using default index: {index_name}"
                    )
                )

        # Get papers to process
        papers = self._get_papers(days, paper_ids_str)

        if not papers.exists():
            self.stdout.write(
                self.style.WARNING("No papers found matching the criteria")
            )
            return

        # Apply limit if specified
        if limit:
            papers = papers[:limit]
            self.stdout.write(self.style.SUCCESS(f"Limited to first {limit} papers"))

        total_count = papers.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Found {total_count} papers to process. Batch size: {batch_size}"
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN MODE - No changes will be made to OpenSearch"
                )
            )

        # Process papers in batches
        processed = 0
        failed = 0
        skipped = 0

        for i in range(0, total_count, batch_size):
            batch = papers[i : i + batch_size]
            self.stdout.write(
                f"\nProcessing batch {i // batch_size + 1} "
                f"({processed + 1}-{min(processed + batch_size, total_count)} of {total_count})"
            )

            batch_results = self._process_batch(
                batch, client, index_name, dry_run, skip_existing
            )

            processed += batch_results["processed"]
            failed += batch_results["failed"]
            skipped += batch_results["skipped"]

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Summary:"))
        self.stdout.write(f"  Total papers: {total_count}")
        self.stdout.write(f"  Processed: {processed}")
        self.stdout.write(f"  Failed: {failed}")
        self.stdout.write(f"  Skipped: {skipped}")
        self.stdout.write("=" * 60)

    def _get_papers(
        self, days: Optional[int], paper_ids_str: Optional[str]
    ) -> QuerySet:
        """Get papers to process based on criteria."""
        papers = Paper.objects.filter(abstract__isnull=False).exclude(abstract="")

        if paper_ids_str:
            # Process specific paper IDs
            try:
                paper_ids = [int(id.strip()) for id in paper_ids_str.split(",")]
                papers = papers.filter(id__in=paper_ids)
            except ValueError:
                raise CommandError(
                    f"Invalid paper IDs format: {paper_ids_str}. Use comma-separated integers."
                )
        elif days:
            # Process papers from the last N days
            cutoff_date = timezone.now() - timedelta(days=days)
            papers = papers.filter(
                Q(created_date__gte=cutoff_date)
                | Q(paper_publish_date__gte=cutoff_date.date())
            )
        else:
            raise CommandError("Either --days or --paper-ids must be specified")

        return papers.order_by("-id")

    def _process_batch(
        self,
        papers: List[Paper],
        client,
        index_name: str,
        dry_run: bool,
        skip_existing: bool,
    ) -> dict:
        """Process a batch of papers."""
        processed = 0
        failed = 0
        skipped = 0

        # Prepare abstracts for embedding
        abstracts = []
        papers_with_abstracts = []

        for paper in papers:
            if not paper.abstract or paper.abstract.strip() == "":
                skipped += 1
                continue

            # Check if vector already exists in OpenSearch (if skip_existing is enabled)
            if skip_existing:
                try:
                    doc = client.get(index=index_name, id=str(paper.id))
                    source = doc.get("_source", {})
                    existing_vector = source.get("abstract_fast_vector")
                    if existing_vector and len(existing_vector) > 0:
                        skipped += 1
                        continue
                except Exception:
                    # Document doesn't exist or error checking, continue processing
                    pass

            # Truncate abstract if too long
            # Most sentence transformers handle up to 512 tokens (roughly 2000-4000 chars)
            # For safety, truncate to 4000 characters
            abstract = paper.abstract[:4000]
            abstracts.append(abstract)
            papers_with_abstracts.append(paper)

        if not abstracts:
            return {"processed": 0, "failed": 0, "skipped": skipped}

        # Generate embeddings using sentence transformers
        try:
            # Encode abstracts in batch
            embeddings = self.model.encode(
                abstracts,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=min(len(abstracts), 32),  # Process in smaller sub-batches
            )
            # Convert numpy array to list of lists
            embeddings = embeddings.tolist()

            # Update OpenSearch documents
            for paper, embedding in zip(papers_with_abstracts, embeddings):

                try:
                    if not dry_run:
                        # Check if document exists in OpenSearch, create if it doesn't (for paper_knn)
                        document_exists = False
                        try:
                            client.get(index=index_name, id=str(paper.id))
                            document_exists = True
                        except Exception:
                            # Document doesn't exist - if using paper_knn, create minimal document
                            if index_name == "paper_knn":
                                try:
                                    # Create minimal document with just ID in paper_knn
                                    client.index(
                                        index=index_name,
                                        id=str(paper.id),
                                        body={"id": paper.id},
                                    )
                                    document_exists = True
                                    self.stdout.write(
                                        f"  Created document for paper {paper.id} in {index_name}"
                                    )
                                except Exception as create_error:
                                    skipped += 1
                                    self.stdout.write(
                                        self.style.WARNING(
                                            f"  Paper {paper.id} not found and failed to create in {index_name}, skipping..."
                                        )
                                    )
                                    continue
                            else:
                                # For paper index, document must exist
                                skipped += 1
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  Paper {paper.id} not found in {index_name}, skipping..."
                                    )
                                )
                                continue

                        # Update OpenSearch document with vector
                        client.update(
                            index=index_name,
                            id=str(paper.id),
                            body={
                                "doc": {
                                    "abstract_fast_vector": embedding,
                                }
                            },
                        )

                    processed += 1
                    if processed % 10 == 0:
                        self.stdout.write(f"  Processed {processed} papers...")

                except Exception as e:
                    failed += 1
                    log_error(
                        e,
                        message=f"Failed to update OpenSearch for paper {paper.id}",
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Failed to update paper {paper.id}: {str(e)}"
                        )
                    )

        except Exception as e:
            failed += len(abstracts)
            log_error(e, message="Failed to generate embeddings")
            self.stdout.write(
                self.style.ERROR(f"Failed to generate embeddings: {str(e)}")
            )

        return {"processed": processed, "failed": failed, "skipped": skipped}
