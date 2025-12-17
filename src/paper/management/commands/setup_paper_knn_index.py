"""
Management command to create the paper_knn index with KNN enabled and copy paper IDs.

This command:
1. Creates a new 'paper_knn' index with KNN enabled
2. Configures abstract_fast_vector (and other vector fields) as knn_vector type
3. Copies paper IDs from 'paper' to 'paper_knn' (creates minimal documents)
4. Vectors will be generated separately using generate_abstract_vectors command

Usage:
    python manage.py setup_paper_knn_index
    python manage.py setup_paper_knn_index --skip-copy-ids
    python manage.py setup_paper_knn_index --force  # Delete existing index first
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django_opensearch_dsl.registries import registry

from search.documents.paper import PaperDocument
from utils.sentry import log_error

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Create paper_knn index with KNN enabled, configure vector fields, "
        "and copy paper IDs from paper index. Vectors will be generated separately."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete existing paper_knn index if it exists before creating (default behavior)",
        )
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="Keep existing paper_knn index if it exists (skip deletion)",
        )
        parser.add_argument(
            "--skip-copy-ids",
            action="store_true",
            help="Skip copying paper IDs from paper index (only create the index)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for copying paper IDs (default: 1000)",
        )
        parser.add_argument(
            "--vector-dimension",
            type=int,
            default=384,
            help="Dimension for knn_vector fields (default: 384 for all-MiniLM-L6-v2)",
        )

    def handle(self, *args, **options):
        force = options.get("force", False)
        keep_existing = options.get("keep_existing", False)
        skip_copy_ids = options.get("skip_copy_ids", False)
        vector_dimension = options.get("vector_dimension", 384)
        batch_size = options.get("batch_size", 1000)

        # Get OpenSearch client
        document = PaperDocument()
        client = document._index._get_connection()
        source_index = PaperDocument._index._name  # "paper"
        target_index = "paper_knn"

        self.stdout.write(f"Setting up {target_index} index...")

        # Check if target index already exists and delete it (unless --keep-existing is set)
        try:
            client.indices.get(index=target_index)
            if keep_existing:
                self.stdout.write(
                    self.style.WARNING(
                        f"Index {target_index} already exists. Keeping it (--keep-existing flag set)."
                    )
                )
                self.stdout.write(
                    "Note: If you want to recreate the index, remove --keep-existing flag."
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"Deleting existing index: {target_index}")
                )
                try:
                    client.indices.delete(index=target_index)
                    self.stdout.write(
                        self.style.SUCCESS(f"Successfully deleted {target_index}")
                    )
                except Exception as e:
                    raise CommandError(
                        f"Failed to delete existing index {target_index}: {str(e)}"
                    )
        except Exception:
            # Index doesn't exist, which is fine
            self.stdout.write(
                f"Index {target_index} does not exist. Will create new one."
            )

        # Get source index mapping to use as base
        try:
            source_mapping = client.indices.get_mapping(index=source_index)
            source_settings = client.indices.get_settings(index=source_index)
        except Exception as e:
            raise CommandError(
                f"Failed to get mapping/settings from source index {source_index}: {str(e)}"
            )

        # Extract mappings and settings
        source_index_data = source_mapping.get(source_index, {})
        source_settings_data = source_settings.get(source_index, {})

        # Build new index settings with KNN enabled
        index_settings = {
            "settings": {
                "index": {
                    "knn": True,  # Enable KNN
                    "knn.algo_param.ef_search": 100,  # HNSW parameter
                },
                "number_of_shards": source_settings_data.get("settings", {})
                .get("index", {})
                .get("number_of_shards", "1"),
                "number_of_replicas": source_settings_data.get("settings", {})
                .get("index", {})
                .get("number_of_replicas", "0"),
            },
            "mappings": source_index_data.get("mappings", {}).copy(),
        }

        # Update mappings to use knn_vector for vector fields
        properties = index_settings["mappings"].get("properties", {})

        # Update abstract_fast_vector to knn_vector
        if "abstract_fast_vector" in properties:
            properties["abstract_fast_vector"] = {
                "type": "knn_vector",
                "dimension": vector_dimension,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                    "parameters": {
                        "ef_construction": 128,
                        "m": 24,
                    },
                },
            }
            self.stdout.write(
                self.style.SUCCESS(
                    f"Configured abstract_fast_vector as knn_vector (dimension: {vector_dimension})"
                )
            )

        # Create the new index
        try:
            self.stdout.write(f"Creating index: {target_index}")
            client.indices.create(index=target_index, body=index_settings)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully created index: {target_index}")
            )
        except Exception as e:
            raise CommandError(f"Failed to create index {target_index}: {str(e)}")

        # Copy paper IDs from source to target (create minimal documents)
        if not skip_copy_ids:
            self.stdout.write(
                f"\nCopying paper IDs from {source_index} to {target_index}..."
            )
            try:
                # Get all paper IDs from source index using scroll API
                self.stdout.write("Fetching paper IDs from source index...")

                # Use scroll to get all IDs efficiently
                scroll_size = batch_size
                paper_ids = []

                # Initial search
                response = client.search(
                    index=source_index,
                    body={
                        "size": scroll_size,
                        "_source": ["id"],  # Only fetch ID field
                        "query": {"match_all": {}},
                    },
                    scroll="2m",  # Keep scroll context alive for 2 minutes
                )

                scroll_id = response.get("_scroll_id")
                hits = response.get("hits", {}).get("hits", [])

                # Collect IDs from first batch
                for hit in hits:
                    paper_id = hit.get("_id")
                    if paper_id:
                        paper_ids.append(paper_id)

                self.stdout.write(f"Found {len(hits)} papers in first batch...")

                # Continue scrolling
                while len(hits) > 0:
                    response = client.scroll(
                        scroll_id=scroll_id,
                        scroll="2m",
                    )
                    scroll_id = response.get("_scroll_id")
                    hits = response.get("hits", {}).get("hits", [])

                    for hit in hits:
                        paper_id = hit.get("_id")
                        if paper_id:
                            paper_ids.append(paper_id)

                    if len(paper_ids) % (batch_size * 10) == 0:
                        self.stdout.write(f"  Collected {len(paper_ids)} paper IDs...")

                # Clear scroll context
                if scroll_id:
                    try:
                        client.clear_scroll(scroll_id=scroll_id)
                    except Exception:
                        pass

                total_ids = len(paper_ids)
                self.stdout.write(
                    self.style.SUCCESS(f"Found {total_ids} paper IDs to copy")
                )

                # Bulk create minimal documents (just ID) in target index
                self.stdout.write(
                    f"Creating minimal documents in {target_index} (batch size: {batch_size})..."
                )

                from opensearchpy.helpers import bulk

                actions = []
                indexed_count = 0

                for paper_id in paper_ids:
                    # Create minimal document with just the ID
                    # The generate_abstract_vectors command will populate the rest
                    try:
                        # Try to convert to int if it's numeric
                        doc_id = int(paper_id) if paper_id.isdigit() else paper_id
                    except (ValueError, AttributeError):
                        doc_id = paper_id

                    action = {
                        "_index": target_index,
                        "_id": str(paper_id),
                        "_source": {
                            "id": doc_id,
                        },
                    }
                    actions.append(action)

                    # Bulk index when batch is full
                    if len(actions) >= batch_size:
                        try:
                            success, failed = bulk(
                                client,
                                actions,
                                chunk_size=batch_size,
                                request_timeout=60,
                            )
                            indexed_count += success
                            if failed:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  Warning: {len(failed)} documents failed in this batch"
                                    )
                                )
                            self.stdout.write(
                                f"  Indexed {indexed_count}/{total_ids} documents..."
                            )
                        except Exception as e:
                            log_error(
                                e,
                                message=f"Failed to bulk index batch of {len(actions)} documents",
                            )
                            self.stdout.write(
                                self.style.WARNING(f"  Warning: Batch failed: {str(e)}")
                            )
                        actions = []

                # Index remaining documents
                if actions:
                    try:
                        success, failed = bulk(
                            client, actions, chunk_size=len(actions), request_timeout=60
                        )
                        indexed_count += success
                        if failed:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  Warning: {len(failed)} documents failed in final batch"
                                )
                            )
                        self.stdout.write(
                            f"  Indexed final {len(actions)} documents (total: {indexed_count})"
                        )
                    except Exception as e:
                        log_error(
                            e,
                            message=f"Failed to bulk index final batch of {len(actions)} documents",
                        )
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Warning: Final batch failed: {str(e)}"
                            )
                        )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully copied {indexed_count} paper IDs to {target_index}"
                    )
                )

                self.stdout.write(
                    "\nNext: Generate vectors using:\n"
                    f"  python manage.py generate_abstract_vectors --index-name {target_index} --days <N>"
                )

            except Exception as e:
                log_error(
                    e,
                    message=f"Failed to copy paper IDs from {source_index} to {target_index}",
                )
                raise CommandError(
                    f"Failed to copy paper IDs: {str(e)}. "
                    "The index was created successfully. You can manually copy IDs or "
                    "use generate_abstract_vectors which will create documents as needed."
                )
        else:
            self.stdout.write(
                self.style.WARNING("Skipping paper ID copy (--skip-copy-ids flag set)")
            )

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Setup completed!"))
        self.stdout.write(f"Index: {target_index}")
        self.stdout.write(f"KNN enabled: Yes")
        self.stdout.write(
            f"Vector fields configured: abstract_fast_vector (dimension: {vector_dimension})"
        )
        if not skip_copy_ids:
            self.stdout.write("Paper IDs copied: Yes")
        else:
            self.stdout.write("Paper IDs copied: No (skipped)")
        self.stdout.write("=" * 60)
        self.stdout.write(
            "\nNext steps:\n"
            "1. Verify the index was created correctly\n"
            "2. Generate vectors for papers:\n"
            f"   python manage.py generate_abstract_vectors --index-name {target_index} --days <N>\n"
            "3. Test the similar_papers endpoint to ensure KNN search works"
        )
