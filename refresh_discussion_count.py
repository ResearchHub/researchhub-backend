#!/usr/bin/env python
"""Refresh stored ``discussion_count`` values.

The helper `RhCommentModel.refresh_related_discussion_count()` recomputes the
count using `rh_threads.get_discussion_aggregates()` and then stores the
result on the underlying Paper / Post / Hypothesis instance.

Usage examples
--------------
• Refresh **all** documents that have at least one comment::

      python refresh_discussion_count.py

• Refresh a **single** unified-document by id::

      python refresh_discussion_count.py --doc-id 4896
"""

import argparse
import os
import sys
from typing import Set

import django

# Ensure we can import project modules when script run from project root
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)
# Also add <root>/src so that `researchhub.settings` can be imported when the
# script is executed from the project root.
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.append(SRC_DIR)

# Point Django to the settings module if not already configured
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "researchhub.settings")

django.setup()

from researchhub_comment.models import RhCommentModel  # noqa: E402
from researchhub_document.models import ResearchhubUnifiedDocument  # noqa: E402


def refresh_counts(doc_id: int | None = None) -> None:  # noqa: D401
    """Iterate through comments, refreshing their related document counts."""

    if doc_id is not None:
        # Limit to comments belonging to the requested unified document.
        try:
            ud = ResearchhubUnifiedDocument.objects.get(id=doc_id)
        except ResearchhubUnifiedDocument.DoesNotExist:
            print(f"UnifiedDocument {doc_id} not found.")
            return

        # Threads are linked through the concrete document (paper/post/etc.).
        concrete = ud.get_document()
        if not hasattr(concrete, "rh_threads"):
            print("Document has no rh_threads relation; nothing to update.")
            return
        thread_ids = concrete.rh_threads.values_list("id", flat=True)
        qs = RhCommentModel.objects.filter(thread_id__in=thread_ids)
    else:
        qs = RhCommentModel.objects.all()

    total_comments = qs.count()
    print(f"Processing {total_comments} comments (doc_id={doc_id or 'ALL'})…")

    processed_docs: Set[int] = set()
    for comment in qs.iterator():
        ud = comment.unified_document
        if ud and ud.id in processed_docs:
            # Already refreshed for this document
            continue
        try:
            comment.refresh_related_discussion_count()
            if ud:
                processed_docs.add(ud.id)
                print(
                    f"Updated discussion_count for doc {ud.id} -> "
                    f"{ud.get_document().discussion_count}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to refresh for comment {comment.id}: {exc}")

    print(f"Finished. Updated {len(processed_docs)} documents.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh discussion_count values.")
    parser.add_argument(
        "--doc-id",
        type=int,
        help="UnifiedDocument id to refresh (processes all if omitted).",
    )
    args = parser.parse_args()

    refresh_counts(doc_id=args.doc_id)
