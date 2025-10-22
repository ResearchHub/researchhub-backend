#!/usr/bin/env python3
"""
Production-safe script to fix legacy headline data model issue.

This script converts Author.headline from object format
{"title": "...", "isPublic": true} to simple string format for
compatibility with OpenSearch indexing.

Usage:
    python fix_headline_data_model.py --dry-run  # Test what would be changed
    python fix_headline_data_model.py            # Apply changes
    python fix_headline_data_model.py --skip-reindex  # Skip re-indexing step
"""

import argparse
import logging
import os
import sys

import django
from django.db import transaction

# Setup Django
sys.path.insert(0, "/workspaces/researchhub-backend/src")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "researchhub.settings")
django.setup()

from search.documents.person import PersonDocument  # noqa: E402
from search.documents.user import UserDocument  # noqa: E402
from user.models import Author, User  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def normalize_headline(headline):
    """
    Normalize headline to string format.

    Args:
        headline: Can be string, dict, or None

    Returns:
        str: Normalized headline string
    """
    if isinstance(headline, dict):
        return headline.get("title", "")
    elif isinstance(headline, str):
        return headline
    else:
        return ""


def analyze_headline_data():
    """Analyze the current state of headline data."""
    logger.info("=== Analyzing Headline Data ===")

    # Count total authors with headlines
    total_authors = Author.objects.exclude(headline__isnull=True).count()
    logger.info(f"Total authors with headlines: {total_authors}")

    # Count by type
    string_count = 0
    object_count = 0
    null_count = 0
    other_count = 0

    for author in Author.objects.exclude(headline__isnull=True).iterator():
        headline = author.headline
        if isinstance(headline, str):
            string_count += 1
        elif isinstance(headline, dict):
            object_count += 1
        elif headline is None:
            null_count += 1
        else:
            other_count += 1

    logger.info(f"  String headlines: {string_count}")
    logger.info(f"  Object headlines: {object_count}")
    logger.info(f"  Null headlines: {null_count}")
    logger.info(f"  Other types: {other_count}")

    return {
        "total": total_authors,
        "string": string_count,
        "object": object_count,
        "null": null_count,
        "other": other_count,
    }


def fix_author_headlines(dry_run=True, batch_size=100):
    """
    Fix all author headlines that are in object format.

    Args:
        dry_run (bool): If True, don't make actual changes
        batch_size (int): Number of records to process in each batch

    Returns:
        dict: Summary of changes made
    """
    logger.info("=== Fixing Author Headline Data Model ===")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"Batch size: {batch_size}")

    # Find all authors with non-null headlines
    authors = Author.objects.exclude(headline__isnull=True)
    total = authors.count()

    logger.info(f"Found {total} authors with headlines")

    fixed_count = 0
    error_count = 0
    skipped_count = 0

    # Process in batches
    for i in range(0, total, batch_size):
        batch = authors[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        logger.info(f"Processing batch {batch_num}/{total_batches}")

        for author in batch:
            try:
                headline = author.headline

                # Check if headline is an object (dict) that needs conversion
                if isinstance(headline, dict):
                    title = headline.get("title", "")
                    logger.debug(f"Author {author.id}: Converting object headline")
                    logger.debug(f"  Old: {headline}")
                    logger.debug(f"  New: {title}")

                    if not dry_run:
                        with transaction.atomic():
                            author.headline = title
                            author.save(update_fields=["headline"])

                    fixed_count += 1
                elif isinstance(headline, str):
                    # Already in correct format
                    skipped_count += 1
                else:
                    # Null or other type - convert to empty string
                    if not dry_run:
                        with transaction.atomic():
                            author.headline = ""
                            author.save(update_fields=["headline"])
                    fixed_count += 1
                    logger.debug(f"Author {author.id}: Converting {type(headline)}")

            except Exception as e:
                logger.error(f"Error processing author {author.id}: {e}")
                error_count += 1

    summary = {
        "total": total,
        "fixed": fixed_count,
        "skipped": skipped_count,
        "errors": error_count,
    }

    logger.info("Summary:")
    logger.info(f"  Total authors: {total}")
    logger.info(f"  Fixed: {fixed_count}")
    logger.info(f"  Skipped: {skipped_count}")
    logger.info(f"  Errors: {error_count}")

    return summary


def reindex_affected_users(dry_run=True, batch_size=50):
    """
    Re-index users whose author profiles had headline fixes.

    Args:
        dry_run (bool): If True, don't make actual changes
        batch_size (int): Number of users to process in each batch

    Returns:
        dict: Summary of re-indexing results
    """
    logger.info("=== Re-indexing Affected Users ===")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"Batch size: {batch_size}")

    # Find users whose author profiles have headlines
    users = User.objects.filter(
        author_profile__headline__isnull=False, is_active=True, is_suspended=False
    ).select_related("author_profile")

    total = users.count()
    logger.info(f"Found {total} users to re-index")

    if dry_run:
        logger.info("Skipping re-index in dry run mode")
        return {"total": total, "success": 0, "errors": 0}

    success_count = 0
    error_count = 0

    # Process in batches
    for i in range(0, total, batch_size):
        batch = users[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        logger.info(f"Re-indexing batch {batch_num}/{total_batches}")

        for user in batch:
            try:
                # Update UserDocument
                user_doc = UserDocument()
                user_doc.update(user, action="index")

                # Update PersonDocument if user has author profile
                if hasattr(user, "author_profile") and user.author_profile:
                    person_doc = PersonDocument()
                    person_doc.update(user.author_profile, action="index")

                success_count += 1
                logger.debug(f"Successfully re-indexed user {user.id}")

            except Exception as e:
                logger.error(f"Error re-indexing user {user.id}: {e}")
                error_count += 1

    summary = {"total": total, "success": success_count, "errors": error_count}

    logger.info("Re-indexing Summary:")
    logger.info(f"  Total users: {total}")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Errors: {error_count}")

    return summary


def verify_fix():
    """Verify that the fix was successful by checking for any remaining object headlines."""  # noqa: E501
    logger.info("=== Verifying Fix ===")

    # Check for any remaining object headlines
    remaining_objects = 0
    for author in Author.objects.exclude(headline__isnull=True).iterator():
        if isinstance(author.headline, dict):
            remaining_objects += 1
            logger.warning(f"Author {author.id} still has object headline")

    if remaining_objects == 0:
        logger.info("✅ All headlines are now in string format")
        return True
    else:
        logger.warning(f"⚠️  {remaining_objects} authors still have object headlines")
        return False


def main():
    """Main function to run the headline data model fix."""
    parser = argparse.ArgumentParser(
        description="Fix headline data model issue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fix_headline_data_model.py --dry-run
  python fix_headline_data_model.py --batch-size 50
  python fix_headline_data_model.py --skip-reindex
  python fix_headline_data_model.py --analyze-only
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Run in dry-run mode (no changes made)"
    )
    parser.add_argument(
        "--skip-reindex", action="store_true", help="Skip re-indexing step"
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Only analyze the data, don't make changes",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for processing (default: 100)",
    )
    parser.add_argument(
        "--reindex-batch-size",
        type=int,
        default=50,
        help="Batch size for re-indexing (default: 50)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Starting headline data model fix")
    logger.info(f"Arguments: {vars(args)}")

    try:
        # Analyze current state
        analysis = analyze_headline_data()

        if args.analyze_only:
            logger.info("Analysis complete. Exiting.")
            return

        # Only proceed if there are object headlines to fix
        if analysis["object"] == 0:
            logger.info("No object headlines found. Nothing to fix.")
            return

        # Fix author headlines
        fix_summary = fix_author_headlines(
            dry_run=args.dry_run, batch_size=args.batch_size
        )

        # Re-index affected users
        if not args.skip_reindex and fix_summary["fixed"] > 0:
            reindex_summary = reindex_affected_users(
                dry_run=args.dry_run, batch_size=args.reindex_batch_size
            )
        else:
            reindex_summary = {"total": 0, "success": 0, "errors": 0}

        # Verify fix
        if not args.dry_run:
            verify_fix()

        # Final summary
        logger.info("=== Final Summary ===")
        logger.info(f"Authors fixed: {fix_summary['fixed']}")
        logger.info(f"Users re-indexed: {reindex_summary['success']}")
        total_errors = fix_summary["errors"] + reindex_summary["errors"]
        logger.info(f"Total errors: {total_errors}")

        if args.dry_run:
            logger.info(
                "⚠️  This was a dry run. Run without --dry-run to apply changes."
            )  # noqa: E501
        else:
            logger.info("✅ Migration complete!")

    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
