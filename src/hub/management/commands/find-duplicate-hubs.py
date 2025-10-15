"""
Find duplicate hubs based on case-insensitive name matching.
"""

import re

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Lower

from discussion.models import Flag
from feed.models import FeedEntry
from hub.models import Hub, HubMembership
from reputation.related_models.distribution import Distribution
from reputation.related_models.paper_reward import HubCitationValue
from reputation.related_models.score import AlgorithmVariables, Score
from researchhub_document.related_models.featured_content_model import FeaturedContent
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.action_model import Action
from user.related_models.follow_model import Follow


class Command(BaseCommand):
    help = (
        "Identify and optionally consolidate duplicate hubs "
        "based on case-insensitive name matching"
    )

    # Available consolidation steps
    AVAILABLE_STEPS = [
        "documents",
        "follows",
        "memberships",
        "flags",
        "scores",
        "distributions",
        "featured_content",
        "citation_values",
        "algorithm_vars",
        "actions",
        "feed_entries",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--consolidate",
            action="store_true",
            help=(
                "Consolidate duplicate hubs to the primary hub "
                "(one without number suffix)"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help=(
                "Show what would be consolidated without making "
                "changes (default: True)"
            ),
        )
        parser.add_argument(
            "--no-dry-run",
            action="store_true",
            help="Actually perform the consolidation (turns off dry-run)",
        )
        parser.add_argument(
            "--include-removed",
            action="store_true",
            help=(
                "Include already removed hubs in consolidation "
                "(useful for fixing partial consolidations)"
            ),
        )
        parser.add_argument(
            "--hard-delete",
            action="store_true",
            help=(
                "Permanently delete duplicate hubs instead of soft delete. "
                "By default, hubs are soft deleted (is_removed=True). "
                "WARNING: This permanently removes hubs from the database!"
            ),
        )
        parser.add_argument(
            "--steps",
            type=str,
            help=(
                "Comma-separated list of steps to run. "
                "Available: documents, follows, memberships, flags, scores, "
                "distributions, featured_content, citation_values, algorithm_vars, "
                "actions, feed_entries. If not specified, all steps will run."
            ),
        )

    def handle(self, *args, **options):
        consolidate = options.get("consolidate", False)
        dry_run = not options.get("no_dry_run", False)
        include_removed = options.get("include_removed", False)
        hard_delete = options.get("hard_delete", False)

        # Auto-enable consolidation when hard-delete is specified
        if hard_delete and not consolidate:
            consolidate = True
            self.stdout.write(
                self.style.WARNING(
                    "Auto-enabling --consolidate mode (hard-delete specified)"
                )
            )

        # Parse steps argument
        steps_arg = options.get("steps")
        if steps_arg:
            # Auto-enable consolidation when steps are specified
            if not consolidate:
                consolidate = True
                self.stdout.write(
                    self.style.WARNING(
                        "Auto-enabling --consolidate mode (steps specified)"
                    )
                )

            self.steps_to_run = set(
                step.strip() for step in steps_arg.split(",") if step.strip()
            )
            # Validate steps
            invalid_steps = self.steps_to_run - set(self.AVAILABLE_STEPS)
            if invalid_steps:
                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid steps: {', '.join(invalid_steps)}. "
                        f"Available: {', '.join(self.AVAILABLE_STEPS)}"
                    )
                )
                return
            self.stdout.write(
                self.style.WARNING(
                    f"Running only selected steps: "
                    f"{', '.join(sorted(self.steps_to_run))}"
                )
            )
        else:
            self.steps_to_run = set(self.AVAILABLE_STEPS)

        # Store hard_delete as instance variable for use in consolidation methods
        self.hard_delete = hard_delete

        self.stdout.write(self.style.SUCCESS("Finding duplicate hubs..."))
        if include_removed:
            self.stdout.write(
                self.style.WARNING("Including already removed hubs in search")
            )
        self.stdout.write("")

        # Find all hubs grouped by lowercase name, with duplicates
        hub_queryset = Hub.objects.all()
        if not include_removed:
            hub_queryset = hub_queryset.filter(is_removed=False)

        duplicates = (
            hub_queryset.values(lower_name=Lower("name"))
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .order_by("-count", "lower_name")
        )

        total_duplicate_groups = duplicates.count()

        if total_duplicate_groups == 0:
            self.stdout.write(self.style.SUCCESS("No duplicate hubs found!"))
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {total_duplicate_groups} groups of duplicate hubs\n"
            )
        )

        if consolidate:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        "=" * 80 + "\n"
                        "DRY RUN MODE - No changes will be made\n"
                        "To apply changes, add --no-dry-run flag\n" + "=" * 80 + "\n"
                    )
                )
            else:
                mode_msg = "⚠️  LIVE MODE - Changes WILL be applied to the database! ⚠️\n"
                if hard_delete:
                    mode_msg += (
                        "🗑️  HARD DELETE enabled - "
                        "Hubs will be PERMANENTLY deleted! 🗑️\n"
                    )
                self.stdout.write(
                    self.style.ERROR("=" * 80 + "\n" + mode_msg + "=" * 80 + "\n")
                )

        total_consolidated = 0
        total_documents_updated = 0
        total_follows_updated = 0
        total_memberships_updated = 0
        total_flags_updated = 0
        total_scores_updated = 0
        total_distributions_updated = 0
        total_featured_content_updated = 0
        total_citation_values_updated = 0
        total_algorithm_vars_updated = 0
        total_actions_updated = 0
        total_feed_entries_updated = 0

        # Track all duplicate hub IDs for file output
        duplicate_hub_ids = []

        # For each duplicate group, show all hubs with that name
        for dup_group in duplicates:
            lower_name = dup_group["lower_name"]
            count = dup_group["count"]

            # Get all hubs with this name (case-insensitive)
            hubs_query = Hub.objects.filter(name__iexact=lower_name)
            if not include_removed:
                hubs_query = hubs_query.filter(is_removed=False)
            hubs_in_group = hubs_query.order_by("id")

            self.stdout.write("=" * 80)
            self.stdout.write(
                self.style.WARNING(
                    f'\nDuplicate Group: "{lower_name}" ({count} hubs)\n'
                )
            )

            # Find the primary hub (one without number suffix in slug)
            primary_hub = self._find_primary_hub(hubs_in_group)

            for hub in hubs_in_group:
                doc_count = hub.related_documents.count()
                is_primary = hub.id == primary_hub.id if primary_hub else False

                self.stdout.write(f"  ID: {hub.id}")
                self.stdout.write(f"  Name: {hub.name}")
                self.stdout.write(f"  Namespace: {hub.namespace or 'None'}")
                self.stdout.write(f"  Paper Count: {hub.paper_count}")
                self.stdout.write(f"  Subscriber Count: {hub.subscriber_count}")
                self.stdout.write(f"  Document Count: {doc_count}")
                self.stdout.write(f"  Slug: {hub.slug}")
                self.stdout.write(f"  Created: {hub.created_date}")
                if is_primary:
                    self.stdout.write(
                        self.style.SUCCESS("  >>> PRIMARY HUB (will keep this one)")
                    )
                self.stdout.write("")

            if consolidate and primary_hub:
                result = self._consolidate_group(hubs_in_group, primary_hub, dry_run)
                total_consolidated += result["hubs_consolidated"]
                total_documents_updated += result["documents_updated"]
                total_follows_updated += result["follows_updated"]
                total_memberships_updated += result["memberships_updated"]
                total_flags_updated += result["flags_updated"]
                total_scores_updated += result["scores_updated"]
                total_distributions_updated += result["distributions_updated"]
                total_featured_content_updated += result["featured_content_updated"]
                total_citation_values_updated += result["citation_values_updated"]
                total_algorithm_vars_updated += result["algorithm_vars_updated"]
                total_actions_updated += result["actions_updated"]
                total_feed_entries_updated += result["feed_entries_updated"]

                # Collect duplicate hub IDs (excluding primary)
                duplicate_hub_ids.extend(result["duplicate_hub_ids"])

        self.stdout.write("=" * 80)
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Summary: Found {total_duplicate_groups} groups with duplicate names"
            )
        )

        if consolidate:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"\nDRY RUN: Would consolidate {total_consolidated} hubs"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_documents_updated} "
                        f"document associations"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_follows_updated} "
                        f"follow relationships"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_memberships_updated} "
                        f"hub memberships"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_flags_updated} flag associations"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would consolidate {total_scores_updated} "
                        f"reputation scores"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_distributions_updated} "
                        f"reputation distributions"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_featured_content_updated} "
                        f"featured content entries"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_citation_values_updated} "
                        f"hub citation values"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_algorithm_vars_updated} "
                        f"algorithm variables"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_actions_updated} user actions"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN: Would update {total_feed_entries_updated} "
                        f"feed entries"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        "\nTo actually perform consolidation, run with "
                        "--consolidate --no-dry-run"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nConsolidated {total_consolidated} hubs successfully!"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_documents_updated} document associations"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_follows_updated} follow relationships"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_memberships_updated} hub memberships"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_flags_updated} flag associations"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Consolidated {total_scores_updated} reputation scores"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_distributions_updated} "
                        f"reputation distributions"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_featured_content_updated} featured content"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_citation_values_updated} citation values"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_algorithm_vars_updated} algorithm variables"
                    )
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Updated {total_actions_updated} user actions")
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Updated {total_feed_entries_updated} feed entries"
                    )
                )

        # Write duplicate hub IDs to file
        if consolidate and duplicate_hub_ids:
            output_file = "duplicates.txt"
            try:
                with open(output_file, "w") as f:
                    f.write("# Duplicate Hub IDs\n")
                    f.write("# These hubs were consolidated and can be removed\n")
                    f.write(f"# Generated: {self._get_timestamp()}\n")
                    f.write(f"# Total: {len(duplicate_hub_ids)} hubs\n")
                    f.write("\n")
                    for hub_id in sorted(duplicate_hub_ids):
                        f.write(f"{hub_id}\n")

                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Wrote {len(duplicate_hub_ids)} duplicate hub IDs "
                        f"to {output_file}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error writing to {output_file}: {str(e)}")
                )

    def _get_timestamp(self):
        """Get current timestamp for file headers"""
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _find_primary_hub(self, hubs):
        """
        Find the primary hub using the following priority:
        1. Hub with the most documents (related_documents count)
        2. Hub without a number suffix in slug
        3. Oldest hub by creation date
        """
        # Annotate each hub with its document count
        hubs_with_counts = []
        for hub in hubs:
            doc_count = hub.related_documents.count()
            hubs_with_counts.append((hub, doc_count))

        # Sort by document count (descending), then by whether it has no suffix
        hubs_with_counts.sort(
            key=lambda x: (
                -x[1],  # Most documents first (negative for descending)
                # No suffix preferred
                not bool(re.search(r"-\d+$", x[0].slug)) if x[0].slug else False,
                x[0].created_date,  # Oldest first as tiebreaker
            ),
            reverse=False,
        )

        if hubs_with_counts:
            primary_hub = hubs_with_counts[0][0]
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Selected primary hub based on: "
                    f"{hubs_with_counts[0][1]} documents"
                )
            )
            return primary_hub

        return hubs.order_by("created_date").first()

    def _consolidate_group(self, hubs_in_group, primary_hub, dry_run):
        """Consolidate all hubs in a group to the primary hub"""
        hubs_consolidated = 0
        documents_updated = 0
        follows_updated = 0
        memberships_updated = 0
        flags_updated = 0
        scores_updated = 0
        distributions_updated = 0
        featured_content_updated = 0
        citation_values_updated = 0
        algorithm_vars_updated = 0
        actions_updated = 0
        feed_entries_updated = 0
        duplicate_hub_ids = []

        duplicate_hubs = hubs_in_group.exclude(id=primary_hub.id)

        for dup_hub in duplicate_hubs:
            # Wrap all consolidation steps in a single transaction
            # Either ALL steps succeed or ALL are rolled back
            try:
                if dry_run:
                    # In dry-run mode, just count without transactions
                    result = self._consolidate_single_hub(
                        dup_hub, primary_hub, dry_run=True
                    )
                else:
                    # In real mode, use atomic transaction
                    with transaction.atomic():
                        result = self._consolidate_single_hub(
                            dup_hub, primary_hub, dry_run=False
                        )

                # Accumulate results
                documents_updated += result["documents"]
                follows_updated += result["follows"]
                memberships_updated += result["memberships"]
                flags_updated += result["flags"]
                scores_updated += result["scores"]
                distributions_updated += result["distributions"]
                featured_content_updated += result["featured_content"]
                citation_values_updated += result["citation_values"]
                algorithm_vars_updated += result["algorithm_vars"]
                actions_updated += result["actions"]
                feed_entries_updated += result["feed_entries"]
                hubs_consolidated += 1

                # Track this duplicate hub ID
                duplicate_hub_ids.append(dup_hub.id)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"\n✗ ERROR consolidating hub {dup_hub.id} "
                        f"({dup_hub.slug}): {str(e)}"
                    )
                )
                if not dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            "  Transaction rolled back - "
                            "no changes applied for this hub"
                        )
                    )
                # Continue with next duplicate hub
                continue

        return {
            "hubs_consolidated": hubs_consolidated,
            "documents_updated": documents_updated,
            "follows_updated": follows_updated,
            "memberships_updated": memberships_updated,
            "flags_updated": flags_updated,
            "scores_updated": scores_updated,
            "distributions_updated": distributions_updated,
            "featured_content_updated": featured_content_updated,
            "citation_values_updated": citation_values_updated,
            "algorithm_vars_updated": algorithm_vars_updated,
            "actions_updated": actions_updated,
            "feed_entries_updated": feed_entries_updated,
            "duplicate_hub_ids": duplicate_hub_ids,
        }

    def _consolidate_single_hub(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate all relationships for a single duplicate hub to primary hub.

        This method is called within a transaction (in non-dry-run mode) to ensure
        atomicity - either ALL consolidations succeed or ALL are rolled back.

        Returns a dictionary with counts of each type of consolidation.
        """
        # Step 1: Consolidate document associations
        doc_count = 0
        if "documents" in self.steps_to_run:
            doc_count = self._consolidate_documents(duplicate_hub, primary_hub, dry_run)

        # Step 2: Consolidate follow relationships
        follow_count = 0
        if "follows" in self.steps_to_run:
            follow_count = self._consolidate_follows(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 3: Consolidate hub memberships
        membership_count = 0
        if "memberships" in self.steps_to_run:
            membership_count = self._consolidate_memberships(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 4: Consolidate flag associations
        flag_count = 0
        if "flags" in self.steps_to_run:
            flag_count = self._consolidate_flags(duplicate_hub, primary_hub, dry_run)

        # Step 5: Consolidate reputation scores
        score_count = 0
        if "scores" in self.steps_to_run:
            score_count = self._consolidate_scores(duplicate_hub, primary_hub, dry_run)

        # Step 6: Consolidate reputation distributions
        distribution_count = 0
        if "distributions" in self.steps_to_run:
            distribution_count = self._consolidate_distributions(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 7: Consolidate featured content
        featured_count = 0
        if "featured_content" in self.steps_to_run:
            featured_count = self._consolidate_featured_content(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 8: Consolidate hub citation values
        citation_count = 0
        if "citation_values" in self.steps_to_run:
            citation_count = self._consolidate_citation_values(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 9: Consolidate algorithm variables
        algo_count = 0
        if "algorithm_vars" in self.steps_to_run:
            algo_count = self._consolidate_algorithm_vars(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 10: Consolidate user actions
        action_count = 0
        if "actions" in self.steps_to_run:
            action_count = self._consolidate_actions(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 11: Consolidate feed entries
        feed_count = 0
        if "feed_entries" in self.steps_to_run:
            feed_count = self._consolidate_feed_entries(
                duplicate_hub, primary_hub, dry_run
            )

        # Step 12: Mark duplicate hub as removed (only if running all steps)
        if self.steps_to_run == set(self.AVAILABLE_STEPS):
            self._mark_hub_as_removed(duplicate_hub, dry_run)
        else:
            self.stdout.write(
                self.style.WARNING(
                    "  ⚠ Skipping hub removal (running selective steps only)"
                )
            )

        return {
            "documents": doc_count,
            "follows": follow_count,
            "memberships": membership_count,
            "flags": flag_count,
            "scores": score_count,
            "distributions": distribution_count,
            "featured_content": featured_count,
            "citation_values": citation_count,
            "algorithm_vars": algo_count,
            "actions": action_count,
            "feed_entries": feed_count,
        }

    def _consolidate_documents(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate document associations from duplicate hub to primary hub.

        Returns the number of documents updated.
        """
        documents = ResearchhubUnifiedDocument.objects.filter(
            hubs=duplicate_hub
        ).distinct()

        doc_count = documents.count()

        if doc_count > 0:
            self.stdout.write(
                f"  → Consolidating hub {duplicate_hub.id} "
                f"({duplicate_hub.slug}): {doc_count} documents"
            )

            if not dry_run:
                for doc in documents:
                    doc.hubs.add(primary_hub)
                    doc.hubs.remove(duplicate_hub)

        return doc_count

    def _consolidate_follows(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate follow relationships from duplicate hub to primary hub.

        If a user already follows the primary hub, delete the duplicate follow.
        Otherwise, update the duplicate follow to point to the primary hub.

        Returns the number of follows updated.
        """
        hub_content_type = ContentType.objects.get_for_model(Hub)
        duplicate_hub_follows = Follow.objects.filter(
            content_type=hub_content_type, object_id=duplicate_hub.id
        )

        follow_count = duplicate_hub_follows.count()

        if follow_count > 0:
            self.stdout.write(
                f"  → Consolidating {follow_count} follows from hub "
                f"{duplicate_hub.id} ({duplicate_hub.slug})"
            )

            if not dry_run:
                for duplicate_follow in duplicate_hub_follows:
                    primary_hub_follow = Follow.objects.filter(
                        user=duplicate_follow.user,
                        content_type=hub_content_type,
                        object_id=primary_hub.id,
                    ).first()

                    if primary_hub_follow:
                        # User already follows primary, delete duplicate
                        duplicate_follow.delete()
                    else:
                        # Update duplicate follow to point to primary
                        duplicate_follow.object_id = primary_hub.id
                        duplicate_follow.save()

        return follow_count

    def _consolidate_memberships(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate hub memberships from duplicate hub to primary hub.

        If a user already has a membership with the primary hub, delete the
        duplicate membership. Otherwise, update the duplicate membership to
        point to the primary hub.

        Returns the number of memberships updated.
        """
        duplicate_memberships = HubMembership.objects.filter(hub=duplicate_hub)

        membership_count = duplicate_memberships.count()

        if membership_count > 0:
            self.stdout.write(
                f"  → Consolidating {membership_count} memberships from hub "
                f"{duplicate_hub.id} ({duplicate_hub.slug})"
            )

            if not dry_run:
                for duplicate_membership in duplicate_memberships:
                    primary_membership = HubMembership.objects.filter(
                        user=duplicate_membership.user, hub=primary_hub
                    ).first()

                    if primary_membership:
                        # User already has membership with primary, delete duplicate
                        duplicate_membership.delete()
                    else:
                        # Update duplicate membership to point to primary
                        duplicate_membership.hub = primary_hub
                        duplicate_membership.save()

        return membership_count

    def _consolidate_flags(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate flag associations from duplicate hub to primary hub.

        Flags can be associated with multiple hubs. This ensures all flags
        associated with the duplicate hub are also associated with the
        primary hub.

        Returns the number of flags updated.
        """
        flags = Flag.objects.filter(hubs=duplicate_hub).distinct()

        flag_count = flags.count()

        if flag_count > 0:
            self.stdout.write(
                f"  → Consolidating hub {duplicate_hub.id} "
                f"({duplicate_hub.slug}): {flag_count} flags"
            )

            if not dry_run:
                for flag in flags:
                    flag.hubs.add(primary_hub)
                    flag.hubs.remove(duplicate_hub)

        return flag_count

    def _consolidate_scores(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate reputation scores from duplicate hub to primary hub.

        For each author with a score in the duplicate hub:
        - If author has a score in primary hub: merge by adding scores together
        - If author has no score in primary hub: update to point to primary hub

        Returns the number of scores processed.
        """
        duplicate_scores = Score.objects.filter(hub=duplicate_hub)
        score_count = duplicate_scores.count()

        if score_count > 0:
            self.stdout.write(
                f"  → Consolidating {score_count} reputation scores from hub "
                f"{duplicate_hub.id} ({duplicate_hub.slug})"
            )

            if not dry_run:
                for dup_score in duplicate_scores:
                    # Check if author already has a score for primary hub
                    primary_score = Score.objects.filter(
                        author=dup_score.author, hub=primary_hub
                    ).first()

                    if primary_score:
                        # Merge: Add duplicate score to primary score
                        primary_score.score += dup_score.score
                        primary_score.save()
                        # Delete the duplicate score
                        dup_score.delete()
                        self.stdout.write(
                            f"    ✓ Merged score for author {dup_score.author.id}: "
                            f"+{dup_score.score} points to primary hub"
                        )
                    else:
                        # No conflict: just update hub reference
                        dup_score.hub = primary_hub
                        dup_score.save()

        return score_count

    def _consolidate_distributions(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate reputation distributions from duplicate hub to primary hub.

        Distributions can be associated with multiple hubs. This ensures all
        distributions associated with the duplicate hub are also associated
        with the primary hub.

        Returns the number of distributions updated.
        """
        distributions = Distribution.objects.filter(hubs=duplicate_hub).distinct()

        distribution_count = distributions.count()

        if distribution_count > 0:
            self.stdout.write(
                f"  → Consolidating hub {duplicate_hub.id} "
                f"({duplicate_hub.slug}): {distribution_count} distributions"
            )

            if not dry_run:
                for distribution in distributions:
                    distribution.hubs.add(primary_hub)
                    distribution.hubs.remove(duplicate_hub)

        return distribution_count

    def _consolidate_featured_content(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate featured content from duplicate hub to primary hub.

        Updates all FeaturedContent entries to point to the primary hub.

        Returns the number of featured content entries updated.
        """
        featured_content = FeaturedContent.objects.filter(hub=duplicate_hub)
        featured_count = featured_content.count()

        if featured_count > 0:
            self.stdout.write(
                f"  → Updating {featured_count} featured content entries "
                f"from hub {duplicate_hub.id} ({duplicate_hub.slug})"
            )

            if not dry_run:
                featured_content.update(hub=primary_hub)

        return featured_count

    def _consolidate_citation_values(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate hub citation values from duplicate hub to primary hub.

        Updates all HubCitationValue entries to point to the primary hub.

        Returns the number of citation value entries updated.
        """
        citation_values = HubCitationValue.objects.filter(hub=duplicate_hub)
        citation_count = citation_values.count()

        if citation_count > 0:
            self.stdout.write(
                f"  → Updating {citation_count} hub citation values "
                f"from hub {duplicate_hub.id} ({duplicate_hub.slug})"
            )

            if not dry_run:
                citation_values.update(hub=primary_hub)

        return citation_count

    def _consolidate_algorithm_vars(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate algorithm variables from duplicate hub to primary hub.

        Updates all AlgorithmVariables entries to point to the primary hub.

        Returns the number of algorithm variable entries updated.
        """
        algorithm_vars = AlgorithmVariables.objects.filter(hub=duplicate_hub)
        algo_count = algorithm_vars.count()

        if algo_count > 0:
            self.stdout.write(
                f"  → Updating {algo_count} algorithm variables "
                f"from hub {duplicate_hub.id} ({duplicate_hub.slug})"
            )

            if not dry_run:
                algorithm_vars.update(hub=primary_hub)

        return algo_count

    def _consolidate_actions(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate user action associations from duplicate hub to primary hub.

        Actions can be associated with multiple hubs. This ensures all actions
        associated with the duplicate hub are also associated with the
        primary hub.

        Returns the number of actions updated.
        """
        actions = Action.objects.filter(hubs=duplicate_hub).distinct()

        action_count = actions.count()

        if action_count > 0:
            self.stdout.write(
                f"  → Consolidating hub {duplicate_hub.id} "
                f"({duplicate_hub.slug}): {action_count} user actions"
            )

            if not dry_run:
                for action in actions:
                    action.hubs.add(primary_hub)
                    action.hubs.remove(duplicate_hub)

        return action_count

    def _consolidate_feed_entries(self, duplicate_hub, primary_hub, dry_run):
        """
        Consolidate feed entry associations from duplicate hub to primary hub.

        Feed entries can be associated with multiple hubs. This ensures all
        feed entries associated with the duplicate hub are also associated
        with the primary hub.

        Returns the number of feed entries updated.
        """
        feed_entries = FeedEntry.objects.filter(hubs=duplicate_hub).distinct()

        feed_count = feed_entries.count()

        if feed_count > 0:
            self.stdout.write(
                f"  → Consolidating hub {duplicate_hub.id} "
                f"({duplicate_hub.slug}): {feed_count} feed entries"
            )

            if not dry_run:
                for feed_entry in feed_entries:
                    feed_entry.hubs.add(primary_hub)
                    feed_entry.hubs.remove(duplicate_hub)

        return feed_count

    def _mark_hub_as_removed(self, duplicate_hub, dry_run):
        """
        Mark a duplicate hub as removed (soft delete) or permanently delete it.

        Logs whether the hub is safe to remove or has dependencies.
        Also force-clears any remaining many-to-many relationships.
        """
        # Force-clear any remaining many-to-many relationships before removal
        if not dry_run:
            # Ensure all documents are removed
            remaining_docs = duplicate_hub.related_documents.all()
            if remaining_docs.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ Force-clearing {remaining_docs.count()} remaining "
                        f"document associations"
                    )
                )
                for doc in remaining_docs:
                    doc.hubs.remove(duplicate_hub)

        subscribers_count = duplicate_hub.subscribers.count()
        has_permissions = duplicate_hub.permissions.exists()
        doc_count = duplicate_hub.related_documents.count()

        if subscribers_count == 0 and not has_permissions and doc_count == 0:
            self.stdout.write(
                f"  → Hub {duplicate_hub.id} ({duplicate_hub.slug}) "
                f"is safe to remove"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ Hub {duplicate_hub.id} ({duplicate_hub.slug}) has "
                    f"subscribers ({subscribers_count}) or permissions or "
                    f"documents ({doc_count}) - "
                    f"marking as removed but keeping data"
                )
            )

        if not dry_run:
            if self.hard_delete:
                # Permanently delete the hub
                duplicate_hub.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  🗑️  Hub {duplicate_hub.id} ({duplicate_hub.slug}) "
                        f"permanently deleted"
                    )
                )
            else:
                # Soft delete: mark as removed
                duplicate_hub.is_removed = True
                duplicate_hub.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Hub {duplicate_hub.id} ({duplicate_hub.slug}) "
                        f"marked as removed"
                    )
                )
