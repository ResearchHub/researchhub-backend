"""
Remove all hubs with namespace='journal' and clean up all related references.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

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
        "Remove all hubs with namespace='journal' and clean up "
        "all related references in the database"
    )

    # Available removal steps
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

    # Slugs to skip (these hubs will not be removed)
    SLUGS_TO_SKIP = {
        "reactions-weekly",
        "scientific-reports",
        "proceedings-of-the-national-academy-of-sciences",
        "plos-one",
        "nature-chemistry",
        "nature-biotechnology",
        "acs-central-science",
        "nature-protocols",
        "geology",
        "arxiv",
        "biorxiv",
        "cell-2",
        "Science",
        "nature-astronomy",
        "chemical-science",
        "nature-geoscience",
        "plos-biology",
        "immunity",
        "ssrn",
        "plos-genetics",
        "journal-of-personality-and-social-psychology",
        "communications-of-the-acm",
        "reviews-of-modern-physics",
        "brain",
        "annals-of-mathematics",
        "energy-environmental-science",
        "nature-ecology-evolution",
        "nature-catalysis",
        "nature-climate-change",
        "science-immunology",
        "joule",
        "genome-research",
        "nature-physics",
        "journal-of-the-american-mathematical-society",
        "science-advances",
        "nature-energy",
        "developmental-cell",
        "current-biology",
        "nature-structural-molecular-biology",
        "applied-physics-letters",
        "authorea",
        "nucleic-acids-research",
        "annals-of-internal-medicine",
        "environmental-science-technology",
        "elife",
        "molecular-psychiatry",
        "global-change-biology",
        "inventiones-mathematicae",
        "chemrxiv",
        "advanced-materials",
        "nature-communications",
        "journal-of-clinical-investigation",
        "ieee-transactions-on-pattern-analysis-and-machine-intelligence",
        "medrxiv",
        "physical-review-letters",
        "molecular-cell",
        "nano-letters",
        "journal-of-neuroscience",
        "the-lancet",
        "american-sociological-review",
        "nature-medicine",
        "science-translational-medicine",
        "american-economic-review",
        "nature-neuroscience",
        "bmj",
        "chemical-reviews",
        "angewandte-chemie",
        "genome-biology",
        "new-england-journal-of-medicine",
        "choice-reviews-online",
        "blood",
        "journal-of-clinical-oncology",
        "cureus",
        "circulation",
        "journal-of-biological-chemistry",
        "cell-reports",
        "american-political-science-review",
        "research-square",
        "osf-preprints",
        "journal-of-the-american-chemical-society",
        "nature-sustainability",
        "nature-machine-intelligence",
        "nature-genetics",
        "jama",
        "cell-metabolism",
        "neuron",
        "nature-1",
        "cell-1",
        "bioinformatics",
        "gastroenterology",
        "cancer-cell-1",
        "psychological-science",
        "acm-computing-surveys",
        "neuron-1",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help=(
                "Show what would be removed without making " "changes (default: True)"
            ),
        )
        parser.add_argument(
            "--no-dry-run",
            action="store_true",
            help="Actually perform the removal (turns off dry-run)",
        )
        parser.add_argument(
            "--hard-delete",
            action="store_true",
            help=(
                "Permanently delete hubs instead of soft delete "
                "(sets is_removed=True by default)"
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
        parser.add_argument(
            "--skip-slugs",
            type=str,
            help=(
                "Comma-separated list of additional hub slugs to skip "
                "(in addition to the built-in exclusion list). "
                "Example: --skip-slugs 'nature,science,cell'"
            ),
        )

    def handle(self, *args, **options):
        dry_run = not options.get("no_dry_run", False)
        hard_delete = options.get("hard_delete", False)

        # Parse additional slugs to skip
        skip_slugs_arg = options.get("skip_slugs")
        additional_skip_slugs = set()
        if skip_slugs_arg:
            additional_skip_slugs = set(
                slug.strip() for slug in skip_slugs_arg.split(",") if slug.strip()
            )
            self.stdout.write(
                self.style.WARNING(
                    f"Additional slugs to skip: "
                    f"{', '.join(sorted(additional_skip_slugs))}"
                )
            )

        # Combine built-in exclusion list with additional skip slugs
        self.slugs_to_skip = self.SLUGS_TO_SKIP | additional_skip_slugs

        # Parse steps argument
        steps_arg = options.get("steps")
        if steps_arg:
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

        self.stdout.write(
            self.style.SUCCESS("Finding hubs with namespace='journal'...")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Exclusion list contains {len(self.slugs_to_skip)} slugs to skip"
            )
        )
        self.stdout.write("")

        # Find all hubs with namespace='journal'
        journal_hubs = Hub.objects.filter(namespace="journal")
        total_hubs = journal_hubs.count()

        if total_hubs == 0:
            self.stdout.write(
                self.style.SUCCESS("No hubs with namespace='journal' found!")
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {total_hubs} hubs with namespace='journal'\n")
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made\n")
            )
        else:
            self.stdout.write(
                self.style.ERROR("REMOVAL MODE - Changes will be applied!\n")
            )
            if hard_delete:
                self.stdout.write(
                    self.style.ERROR(
                        "HARD DELETE enabled - Hubs will be permanently deleted!\n"
                    )
                )

        total_hubs_removed = 0
        total_hubs_skipped = 0
        total_documents_updated = 0
        total_follows_deleted = 0
        total_memberships_deleted = 0
        total_flags_updated = 0
        total_scores_deleted = 0
        total_distributions_deleted = 0
        total_featured_content_deleted = 0
        total_citation_values_deleted = 0
        total_algorithm_vars_deleted = 0
        total_actions_updated = 0
        total_feed_entries_updated = 0

        # Process each journal hub
        for hub in journal_hubs:
            # Skip hubs in the exclusion list
            if hub.slug in self.slugs_to_skip:
                self.stdout.write(
                    self.style.WARNING(
                        f'Skipping hub: "{hub.name}" (ID: {hub.id}, slug: {hub.slug}) '
                        f"- in exclusion list"
                    )
                )
                total_hubs_skipped += 1
                continue
            self.stdout.write("=" * 80)
            self.stdout.write(
                self.style.WARNING(f'\nProcessing Hub: "{hub.name}" (ID: {hub.id})\n')
            )
            self.stdout.write(f"  Namespace: {hub.namespace}")
            self.stdout.write(f"  Slug: {hub.slug}")
            self.stdout.write(f"  Paper Count: {hub.paper_count}")
            self.stdout.write(f"  Subscriber Count: {hub.subscriber_count}")
            self.stdout.write(f"  Document Count: {hub.related_documents.count()}")
            self.stdout.write(f"  Created: {hub.created_date}")
            self.stdout.write("")

            try:
                if dry_run:
                    # In dry-run mode, just count without transactions
                    result = self._remove_hub_references(hub, dry_run=True)
                else:
                    # In real mode, use atomic transaction
                    with transaction.atomic():
                        result = self._remove_hub_references(hub, dry_run=False)
                        # Delete or soft delete the hub (only if running all steps)
                        if self.steps_to_run == set(self.AVAILABLE_STEPS):
                            # Force-clear any remaining document associations
                            remaining_docs = hub.related_documents.all()
                            if remaining_docs.exists():
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  ⚠ Force-clearing {remaining_docs.count()} "
                                        f"remaining document associations"
                                    )
                                )
                                for doc in remaining_docs:
                                    doc.hubs.remove(hub)

                            if hard_delete:
                                hub.delete()
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"  ✓ Hub {hub.id} permanently deleted"
                                    )
                                )
                            else:
                                hub.is_removed = True
                                hub.save()
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"  ✓ Hub {hub.id} marked as removed"
                                    )
                                )
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    "  ⚠ Skipping hub removal "
                                    "(running selective steps only)"
                                )
                            )

                # Accumulate results
                total_documents_updated += result["documents"]
                total_follows_deleted += result["follows"]
                total_memberships_deleted += result["memberships"]
                total_flags_updated += result["flags"]
                total_scores_deleted += result["scores"]
                total_distributions_deleted += result["distributions"]
                total_featured_content_deleted += result["featured_content"]
                total_citation_values_deleted += result["citation_values"]
                total_algorithm_vars_deleted += result["algorithm_vars"]
                total_actions_updated += result["actions"]
                total_feed_entries_updated += result["feed_entries"]
                total_hubs_removed += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"\n✗ ERROR removing hub {hub.id} ({hub.slug}): {str(e)}"
                    )
                )
                if not dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            "  Transaction rolled back - "
                            "no changes applied for this hub"
                        )
                    )
                # Continue with next hub
                continue

        self.stdout.write("=" * 80)
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Summary: Found {total_hubs} journal hubs")
        )
        if total_hubs_skipped > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {total_hubs_skipped} hubs (in exclusion list)"
                )
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"\nDRY RUN: Would remove {total_hubs_removed} hubs")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would update {total_documents_updated} "
                    f"document associations"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {total_follows_deleted} "
                    f"follow relationships"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {total_memberships_deleted} "
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
                    f"DRY RUN: Would delete {total_scores_deleted} reputation scores"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {total_distributions_deleted} "
                    f"reputation distributions"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {total_featured_content_deleted} "
                    f"featured content entries"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {total_citation_values_deleted} "
                    f"hub citation values"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {total_algorithm_vars_deleted} "
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
                    f"DRY RUN: Would update {total_feed_entries_updated} feed entries"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    "\nTo actually perform removal, run with --no-dry-run"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nRemoved {total_hubs_removed} hubs successfully!")
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {total_documents_updated} document associations"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total_follows_deleted} follow relationships"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total_memberships_deleted} hub memberships"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(f"Updated {total_flags_updated} flag associations")
            )
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {total_scores_deleted} reputation scores")
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total_distributions_deleted} reputation distributions"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total_featured_content_deleted} featured content entries"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total_citation_values_deleted} citation values"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total_algorithm_vars_deleted} algorithm variables"
                )
            )
            self.stdout.write(
                self.style.SUCCESS(f"Updated {total_actions_updated} user actions")
            )
            self.stdout.write(
                self.style.SUCCESS(f"Updated {total_feed_entries_updated} feed entries")
            )

    def _remove_hub_references(self, hub, dry_run):
        """
        Remove all references to a hub from related tables.

        This method is called within a transaction (in non-dry-run mode) to ensure
        atomicity - either ALL deletions succeed or ALL are rolled back.

        Returns a dictionary with counts of each type of deletion/update.
        """
        # Step 1: Remove document associations
        doc_count = 0
        if "documents" in self.steps_to_run:
            doc_count = self._remove_document_associations(hub, dry_run)

        # Step 2: Delete follow relationships
        follow_count = 0
        if "follows" in self.steps_to_run:
            follow_count = self._delete_follows(hub, dry_run)

        # Step 3: Delete hub memberships
        membership_count = 0
        if "memberships" in self.steps_to_run:
            membership_count = self._delete_memberships(hub, dry_run)

        # Step 4: Remove flag associations
        flag_count = 0
        if "flags" in self.steps_to_run:
            flag_count = self._remove_flag_associations(hub, dry_run)

        # Step 5: Delete reputation scores
        score_count = 0
        if "scores" in self.steps_to_run:
            score_count = self._delete_scores(hub, dry_run)

        # Step 6: Delete reputation distributions
        distribution_count = 0
        if "distributions" in self.steps_to_run:
            distribution_count = self._delete_distributions(hub, dry_run)

        # Step 7: Delete featured content
        featured_count = 0
        if "featured_content" in self.steps_to_run:
            featured_count = self._delete_featured_content(hub, dry_run)

        # Step 8: Delete hub citation values
        citation_count = 0
        if "citation_values" in self.steps_to_run:
            citation_count = self._delete_citation_values(hub, dry_run)

        # Step 9: Delete algorithm variables
        algo_count = 0
        if "algorithm_vars" in self.steps_to_run:
            algo_count = self._delete_algorithm_vars(hub, dry_run)

        # Step 10: Remove action associations
        action_count = 0
        if "actions" in self.steps_to_run:
            action_count = self._remove_action_associations(hub, dry_run)

        # Step 11: Remove feed entry associations
        feed_count = 0
        if "feed_entries" in self.steps_to_run:
            feed_count = self._remove_feed_entry_associations(hub, dry_run)

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

    def _remove_document_associations(self, hub, dry_run):
        """
        Remove document associations with this hub (many-to-many).

        Returns the number of documents updated.
        """
        documents = ResearchhubUnifiedDocument.objects.filter(hubs=hub).distinct()
        doc_count = documents.count()

        if doc_count > 0:
            self.stdout.write(
                f"  → Removing {doc_count} document associations from hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                for doc in documents:
                    doc.hubs.remove(hub)

        return doc_count

    def _delete_follows(self, hub, dry_run):
        """
        Delete follow relationships for this hub.

        Returns the number of follows deleted.
        """
        hub_content_type = ContentType.objects.get_for_model(Hub)
        follows = Follow.objects.filter(content_type=hub_content_type, object_id=hub.id)

        follow_count = follows.count()

        if follow_count > 0:
            self.stdout.write(
                f"  → Deleting {follow_count} follows for hub " f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                follows.delete()

        return follow_count

    def _delete_memberships(self, hub, dry_run):
        """
        Delete hub memberships for this hub.

        Returns the number of memberships deleted.
        """
        memberships = HubMembership.objects.filter(hub=hub)
        membership_count = memberships.count()

        if membership_count > 0:
            self.stdout.write(
                f"  → Deleting {membership_count} memberships for hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                memberships.delete()

        return membership_count

    def _remove_flag_associations(self, hub, dry_run):
        """
        Remove flag associations with this hub (many-to-many).

        Returns the number of flags updated.
        """
        flags = Flag.objects.filter(hubs=hub).distinct()
        flag_count = flags.count()

        if flag_count > 0:
            self.stdout.write(
                f"  → Removing {flag_count} flag associations from hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                for flag in flags:
                    flag.hubs.remove(hub)

        return flag_count

    def _delete_scores(self, hub, dry_run):
        """
        Delete reputation scores associated with this hub.

        Returns the number of scores deleted.
        """
        scores = Score.objects.filter(hub=hub)
        score_count = scores.count()

        if score_count > 0:
            self.stdout.write(
                f"  → Deleting {score_count} reputation scores for hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                scores.delete()

        return score_count

    def _delete_distributions(self, hub, dry_run):
        """
        Delete reputation distributions associated with this hub (many-to-many).

        Returns the number of distributions updated.
        """
        distributions = Distribution.objects.filter(hubs=hub).distinct()
        distribution_count = distributions.count()

        if distribution_count > 0:
            self.stdout.write(
                f"  → Removing {distribution_count} distribution associations "
                f"from hub {hub.id} ({hub.slug})"
            )

            if not dry_run:
                for distribution in distributions:
                    distribution.hubs.remove(hub)

        return distribution_count

    def _delete_featured_content(self, hub, dry_run):
        """
        Delete featured content associated with this hub.

        Returns the number of featured content entries deleted.
        """
        featured_content = FeaturedContent.objects.filter(hub=hub)
        featured_count = featured_content.count()

        if featured_count > 0:
            self.stdout.write(
                f"  → Deleting {featured_count} featured content entries for hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                featured_content.delete()

        return featured_count

    def _delete_citation_values(self, hub, dry_run):
        """
        Delete hub citation values associated with this hub.

        Returns the number of citation value entries deleted.
        """
        citation_values = HubCitationValue.objects.filter(hub=hub)
        citation_count = citation_values.count()

        if citation_count > 0:
            self.stdout.write(
                f"  → Deleting {citation_count} hub citation values for hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                citation_values.delete()

        return citation_count

    def _delete_algorithm_vars(self, hub, dry_run):
        """
        Delete algorithm variables associated with this hub.

        Returns the number of algorithm variable entries deleted.
        """
        algorithm_vars = AlgorithmVariables.objects.filter(hub=hub)
        algo_count = algorithm_vars.count()

        if algo_count > 0:
            self.stdout.write(
                f"  → Deleting {algo_count} algorithm variables for hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                algorithm_vars.delete()

        return algo_count

    def _remove_action_associations(self, hub, dry_run):
        """
        Remove action associations with this hub (many-to-many).

        Returns the number of actions updated.
        """
        actions = Action.objects.filter(hubs=hub).distinct()
        action_count = actions.count()

        if action_count > 0:
            self.stdout.write(
                f"  → Removing {action_count} action associations from hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                for action in actions:
                    action.hubs.remove(hub)

        return action_count

    def _remove_feed_entry_associations(self, hub, dry_run):
        """
        Remove feed entry associations with this hub (many-to-many).

        Returns the number of feed entries updated.
        """
        feed_entries = FeedEntry.objects.filter(hubs=hub).distinct()
        feed_count = feed_entries.count()

        if feed_count > 0:
            self.stdout.write(
                f"  → Removing {feed_count} feed entry associations from hub "
                f"{hub.id} ({hub.slug})"
            )

            if not dry_run:
                for feed_entry in feed_entries:
                    feed_entry.hubs.remove(hub)

        return feed_count
