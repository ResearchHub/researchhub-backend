"""
Management command to test and compare hot scores.

This command allows testing the new hot score algorithm on real data,
comparing results, and exporting detailed breakdowns for analysis.

Usage:
    python manage.py test_hot_scores --limit 20
    python manage.py test_hot_scores --content-type paper --csv output.csv
    python manage.py test_hot_scores --show-components
    python manage.py test_hot_scores --feed-entry-id 12345
    python manage.py test_hot_scores --unified-document-id 67890
"""

import csv

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from feed.hot_score import (
    HOT_SCORE_CONFIG,
    calculate_hot_score_for_item,
    get_age_hours,
    get_altmetric_score,
    get_comment_count,
    get_freshness_multiplier,
    get_fundraise_amount,
    get_peer_review_count,
    get_total_bounty_amount,
    get_total_tip_amount,
    get_total_upvotes,
)
from feed.hot_score_DEPRECATED import calculate_hot_score_for_item_DEPRECATED
from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class Command(BaseCommand):
    help = "Test and compare hot scores with detailed component breakdown"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Number of top entries to display",
        )
        parser.add_argument(
            "--content-type",
            type=str,
            choices=["paper", "post", "all"],
            default="all",
            help="Filter by content type",
        )
        parser.add_argument(
            "--show-components",
            action="store_true",
            help="Show detailed component breakdown",
        )
        parser.add_argument(
            "--csv",
            type=str,
            help="Export results to CSV file",
        )
        parser.add_argument(
            "--unified-document-id",
            type=int,
            help="Debug a specific unified document by ID",
        )
        parser.add_argument(
            "--feed-entry-id",
            type=int,
            help="Debug a specific feed entry by ID",
        )
        # Simulation parameters (default 0 = use actual values)
        parser.add_argument(
            "--sim-upvotes",
            type=int,
            default=0,
            help="Simulate upvote count (0 = use actual)",
        )
        parser.add_argument(
            "--sim-comments",
            type=int,
            default=0,
            help="Simulate comment count (0 = use actual)",
        )
        parser.add_argument(
            "--sim-tips",
            type=float,
            default=0,
            help="Simulate tip amount (0 = use actual)",
        )
        parser.add_argument(
            "--sim-bounty",
            type=float,
            default=0,
            help="Simulate bounty amount (0 = use actual)",
        )
        parser.add_argument(
            "--sim-urgent-bounty",
            action="store_true",
            help="Simulate urgent bounty flag",
        )
        parser.add_argument(
            "--sim-peer-reviews",
            type=int,
            default=0,
            help="Simulate peer review count (0 = use actual)",
        )
        parser.add_argument(
            "--sim-altmetric",
            type=float,
            default=0,
            help="Simulate altmetric score (0 = use actual)",
        )
        parser.add_argument(
            "--sim-age-hours",
            type=float,
            default=0,
            help="Simulate age in hours (0 = use actual)",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        content_type_filter = options["content_type"]
        show_components = options["show_components"]
        csv_file = options["csv"]
        unified_document_id = options.get("unified_document_id")
        feed_entry_id = options.get("feed_entry_id")

        # Build simulation parameters dict
        sim_params = {
            "upvotes": options.get("sim_upvotes", 0),
            "comments": options.get("sim_comments", 0),
            "tips": options.get("sim_tips", 0),
            "bounty": options.get("sim_bounty", 0),
            "urgent_bounty": options.get("sim_urgent_bounty", False),
            "peer_reviews": options.get("sim_peer_reviews", 0),
            "altmetric": options.get("sim_altmetric", 0),
            "age_hours": options.get("sim_age_hours", 0),
        }

        # Special handling for specific feed entry debugging
        if feed_entry_id:
            self._debug_feed_entry(feed_entry_id, sim_params)
            return

        # Special handling for specific unified document debugging
        if unified_document_id:
            self._debug_unified_document(unified_document_id, sim_params)
            return

        self.stdout.write(self.style.SUCCESS("Testing Hot Score Algorithm"))
        self.stdout.write("=" * 80)
        self.stdout.write("")

        # Build queryset
        queryset = FeedEntry.objects.select_related(
            "content_type", "unified_document"
        ).prefetch_related("item")

        # Filter by content type
        if content_type_filter == "paper":
            paper_ct = ContentType.objects.get_for_model(Paper)
            queryset = queryset.filter(content_type=paper_ct)
        elif content_type_filter == "post":
            post_ct = ContentType.objects.get_for_model(ResearchhubPost)
            queryset = queryset.filter(content_type=post_ct)

        # Get entries with existing hot scores
        queryset = queryset.exclude(hot_score__isnull=True).order_by("-hot_score")[
            : limit * 2
        ]

        results = []

        self.stdout.write(f"Analyzing {len(queryset)} feed entries...")
        self.stdout.write("")

        for feed_entry in queryset:
            try:
                item = feed_entry.item
                if not item:
                    continue

                unified_doc = feed_entry.unified_document

                # Calculate both DEPRECATED (old) and v2 (new) hot scores
                v1_score = calculate_hot_score_for_item_DEPRECATED(feed_entry)
                v2_score = calculate_hot_score_for_item(feed_entry)

                # Get component breakdown for v2
                components = self._get_components(item, unified_doc, feed_entry)

                results.append(
                    {
                        "feed_entry": feed_entry,
                        "item": item,
                        "v1_score": v1_score,
                        "v2_score": v2_score,
                        "stored_v1": feed_entry.hot_score,
                        "stored_v2": feed_entry.hot_score_v2,
                        "components": components,
                    }
                )

            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"Error processing entry {feed_entry.id}: {e}")
                )
                continue

        # Sort by v2 score
        results.sort(key=lambda x: x["v2_score"], reverse=True)
        results = results[:limit]

        # Display results
        self._display_results(results, show_components)

        # Export to CSV if requested
        if csv_file:
            self._export_csv(results, csv_file)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Analyzed {len(results)} entries"))

    def _get_components(self, item, unified_doc, feed_entry):
        """Get detailed component breakdown for an item."""
        from feed.hot_score_breakdown import get_hot_score_breakdown

        # Use stored breakdown if available, otherwise calculate
        if (
            hasattr(feed_entry, "hot_score_breakdown_v2")
            and feed_entry.hot_score_breakdown_v2
        ):
            breakdown = feed_entry.hot_score_breakdown_v2.breakdown_data

            # Convert breakdown format to legacy format for compatibility
            return {
                "altmetric": breakdown["signals"]["altmetric"],
                "bounty": breakdown["signals"]["bounty"],
                "tip": breakdown["signals"]["tip"],
                "peer_review": breakdown["signals"]["peer_review"],
                "upvote": breakdown["signals"]["upvote"],
                "comment": breakdown["signals"]["comment"],
                "age_hours": breakdown["time_factors"]["age_hours"],
                "freshness_multiplier": breakdown["time_factors"][
                    "freshness_multiplier"
                ],
                "engagement_score": breakdown["calculation"]["engagement_score"],
                "time_denominator": breakdown["calculation"]["time_denominator"],
            }

        # Fallback: calculate if not stored (for old entries)
        breakdown = get_hot_score_breakdown(feed_entry)

        return {
            "altmetric": breakdown["signals"]["altmetric"],
            "bounty": breakdown["signals"]["bounty"],
            "tip": breakdown["signals"]["tip"],
            "peer_review": breakdown["signals"]["peer_review"],
            "upvote": breakdown["signals"]["upvote"],
            "comment": breakdown["signals"]["comment"],
            "age_hours": breakdown["time_factors"]["age_hours"],
            "freshness_multiplier": breakdown["time_factors"]["freshness_multiplier"],
            "engagement_score": breakdown["calculation"]["engagement_score"],
            "time_denominator": breakdown["calculation"]["time_denominator"],
        }

    def _get_components_with_simulation(
        self, item, unified_doc, feed_entry, sim_params
    ):
        """
        Get detailed component breakdown with optional simulated values.

        NOTE: This function intentionally duplicates calculation logic from
        calculate_hot_score() because it needs to support "what-if" scenarios
        where individual signal values are overridden for testing purposes.
        We cannot use calculate_hot_score() directly because we need to:
        1. Get actual values first
        2. Override specific values with simulation parameters
        3. Recalculate components with the overridden values
        """
        import math

        config = HOT_SCORE_CONFIG["signals"]

        # Gather actual signals using new feed_entry-based API
        altmetric = get_altmetric_score(feed_entry)
        bounty_amount, has_urgent_bounty = get_total_bounty_amount(feed_entry)
        tip_amount = get_total_tip_amount(feed_entry)
        fundraise_amount = get_fundraise_amount(feed_entry)
        if fundraise_amount > 0:
            tip_amount += fundraise_amount

        peer_review_count = get_peer_review_count(feed_entry)
        upvote_count = get_total_upvotes(feed_entry)
        comment_count = get_comment_count(feed_entry)
        age_hours = get_age_hours(feed_entry)

        # Override with simulation parameters if provided
        if sim_params:
            if sim_params.get("altmetric", 0) > 0:
                altmetric = sim_params["altmetric"]
            if sim_params.get("bounty", 0) > 0:
                bounty_amount = sim_params["bounty"]
            if sim_params.get("urgent_bounty", False):
                has_urgent_bounty = True
            if sim_params.get("tips", 0) > 0:
                tip_amount = sim_params["tips"]
            if sim_params.get("peer_reviews", 0) > 0:
                peer_review_count = sim_params["peer_reviews"]
            if sim_params.get("upvotes", 0) > 0:
                upvote_count = sim_params["upvotes"]
            if sim_params.get("comments", 0) > 0:
                comment_count = sim_params["comments"]
            if sim_params.get("age_hours", 0) > 0:
                age_hours = sim_params["age_hours"]

        # Calculate freshness multiplier after overrides (depends on age_hours)
        freshness_multiplier = get_freshness_multiplier(feed_entry, age_hours)

        # Calculate component scores (same logic as calculate_hot_score)
        altmetric_component = (
            math.log(altmetric + 1, config["altmetric"]["log_base"])
            * config["altmetric"]["weight"]
        )

        bounty_multiplier = (
            config["bounty"]["urgency_multiplier"] if has_urgent_bounty else 1.0
        )
        bounty_component = (
            math.log(bounty_amount + 1, config["bounty"]["log_base"])
            * config["bounty"]["weight"]
            * bounty_multiplier
        )

        tip_component = (
            math.log(tip_amount + 1, config["tip"]["log_base"])
            * config["tip"]["weight"]
        )

        peer_review_component = (
            math.log(peer_review_count + 1, config["peer_review"]["log_base"])
            * config["peer_review"]["weight"]
        )

        upvote_component = (
            math.log(upvote_count + 1, config["upvote"]["log_base"])
            * config["upvote"]["weight"]
        )

        comment_component = (
            math.log(comment_count + 1, config["comment"]["log_base"])
            * config["comment"]["weight"]
        )

        engagement_score = (
            altmetric_component
            + bounty_component
            + tip_component
            + peer_review_component
            + upvote_component
            + comment_component
        ) * freshness_multiplier

        decay_config = HOT_SCORE_CONFIG["time_decay"]
        denominator = math.pow(
            age_hours + decay_config["base_hours"], decay_config["gravity"]
        )

        return {
            "altmetric": {
                "raw": altmetric,
                "component": altmetric_component,
            },
            "bounty": {
                "raw": bounty_amount,
                "urgent": has_urgent_bounty,
                "component": bounty_component,
            },
            "tip": {"raw": tip_amount, "component": tip_component},
            "peer_review": {
                "raw": peer_review_count,
                "component": peer_review_component,
            },
            "upvote": {"raw": upvote_count, "component": upvote_component},
            "comment": {"raw": comment_count, "component": comment_component},
            "age_hours": age_hours,
            "freshness_multiplier": freshness_multiplier,
            "engagement_score": engagement_score,
            "time_denominator": denominator,
        }

    def _display_results(self, results, show_components):
        """Display results in a formatted table."""
        self.stdout.write(
            f"{'Rank':<6} {'Title':<35} {'Type':<6} "
            f"{'V1':<10} {'V2':<10} {'Change':<15}"
        )
        self.stdout.write("-" * 92)

        for i, result in enumerate(results, 1):
            item = result["item"]
            v1_score = result["v1_score"]
            v2_score = result["v2_score"]

            # Get title
            title = getattr(item, "title", "")
            if not title:
                title = getattr(item, "paper_title", "")
            if not title:
                title = f"Item #{item.id}"
            title = title[:32] + "..." if len(title) > 35 else title

            # Get type
            item_type = "Paper" if isinstance(item, Paper) else "Post"

            # Calculate change from v1 to v2
            change = v2_score - v1_score
            change_pct = (change / v1_score * 100) if v1_score > 0 else 0
            change_str = f"{change:+.0f} ({change_pct:+.1f}%)"

            self.stdout.write(
                f"{i:<6} {title:<35} {item_type:<6} "
                f"{v1_score:<10.0f} {v2_score:<10.0f} {change_str:<15}"
            )

            # Show component breakdown if requested
            if show_components:
                self._display_components(result["components"])
                self.stdout.write("")

    def _display_components(self, components):
        """Display component breakdown."""
        self.stdout.write("  Components:")
        self.stdout.write(
            f"    Altmetric:    {components['altmetric']['raw']:>8.1f} "
            f"→ {components['altmetric']['component']:>8.2f}"
        )
        bounty_marker = " (URGENT!)" if components["bounty"]["urgent"] else ""
        self.stdout.write(
            f"    Bounty:       {components['bounty']['raw']:>8.1f} "
            f"→ {components['bounty']['component']:>8.2f}{bounty_marker}"
        )
        self.stdout.write(
            f"    Tips:         {components['tip']['raw']:>8.1f} "
            f"→ {components['tip']['component']:>8.2f}"
        )
        self.stdout.write(
            f"    Peer Reviews: {components['peer_review']['raw']:>8.0f} "
            f"→ {components['peer_review']['component']:>8.2f}"
        )
        self.stdout.write(
            f"    Upvotes:      {components['upvote']['raw']:>8.0f} "
            f"→ {components['upvote']['component']:>8.2f}"
        )
        self.stdout.write(
            f"    Comments:     {components['comment']['raw']:>8.0f} "
            f"→ {components['comment']['component']:>8.2f}"
        )
        self.stdout.write(f"    Age (hours):  {components['age_hours']:>8.1f}")
        freshness = components["freshness_multiplier"]
        self.stdout.write(f"    Multiplier:   {freshness:>8.2f}")
        self.stdout.write(f"    Engagement:   {components['engagement_score']:>8.2f}")
        self.stdout.write(f"    Time Decay:   {components['time_denominator']:>8.2f}")

    def _export_csv(self, results, csv_file):
        """Export results to CSV."""
        self.stdout.write("")
        self.stdout.write(f"Exporting to {csv_file}...")

        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)

            # Header
            writer.writerow(
                [
                    "Rank",
                    "ID",
                    "Type",
                    "Title",
                    "V1 Score (Old)",
                    "V2 Score (New)",
                    "Stored V1",
                    "Stored V2",
                    "Change (V2-V1)",
                    "Change %",
                    "Altmetric Raw",
                    "Altmetric Component",
                    "Bounty Raw",
                    "Bounty Urgent",
                    "Bounty Component",
                    "Tip Raw",
                    "Tip Component",
                    "Peer Review Raw",
                    "Peer Review Component",
                    "Upvote Raw",
                    "Upvote Component",
                    "Comment Raw",
                    "Comment Component",
                    "Age Hours",
                    "Freshness Multiplier",
                    "Engagement Score",
                    "Time Denominator",
                ]
            )

            # Data
            for i, result in enumerate(results, 1):
                item = result["item"]
                v1_score = result["v1_score"]
                v2_score = result["v2_score"]
                stored_v1 = result["stored_v1"]
                stored_v2 = result["stored_v2"]
                comp = result["components"]

                title = getattr(item, "title", "")
                if not title:
                    title = getattr(item, "paper_title", "")

                item_type = "Paper" if isinstance(item, Paper) else "Post"

                change = v2_score - v1_score
                change_pct = (change / v1_score * 100) if v1_score > 0 else 0

                writer.writerow(
                    [
                        i,
                        item.id,
                        item_type,
                        title,
                        v1_score,
                        v2_score,
                        stored_v1,
                        stored_v2,
                        change,
                        change_pct,
                        comp["altmetric"]["raw"],
                        comp["altmetric"]["component"],
                        comp["bounty"]["raw"],
                        comp["bounty"]["urgent"],
                        comp["bounty"]["component"],
                        comp["tip"]["raw"],
                        comp["tip"]["component"],
                        comp["peer_review"]["raw"],
                        comp["peer_review"]["component"],
                        comp["upvote"]["raw"],
                        comp["upvote"]["component"],
                        comp["comment"]["raw"],
                        comp["comment"]["component"],
                        comp["age_hours"],
                        comp["freshness_multiplier"],
                        comp["engagement_score"],
                        comp["time_denominator"],
                    ]
                )

        self.stdout.write(self.style.SUCCESS(f"Exported to {csv_file}"))

    def _debug_feed_entry(self, feed_entry_id, sim_params=None):
        """Debug a specific feed entry with detailed breakdown."""
        # Check if any simulation parameters are active
        has_simulation = sim_params and any(
            [
                sim_params.get("upvotes", 0) > 0,
                sim_params.get("comments", 0) > 0,
                sim_params.get("tips", 0) > 0,
                sim_params.get("bounty", 0) > 0,
                sim_params.get("urgent_bounty", False),
                sim_params.get("peer_reviews", 0) > 0,
                sim_params.get("altmetric", 0) > 0,
                sim_params.get("age_hours", 0) > 0,
            ]
        )

        title_text = f"Debugging Feed Entry ID: {feed_entry_id}"
        if has_simulation:
            title_text += " (WITH SIMULATION)"
        self.stdout.write(self.style.SUCCESS(title_text))
        self.stdout.write("=" * 80)
        self.stdout.write("")

        try:
            feed_entry = (
                FeedEntry.objects.select_related("content_type", "unified_document")
                .prefetch_related("item")
                .get(id=feed_entry_id)
            )
        except FeedEntry.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Feed entry with ID {feed_entry_id} not found")
            )
            return

        item = feed_entry.item
        if not item:
            self.stdout.write(self.style.ERROR("Feed entry has no associated item"))
            return

        unified_doc = feed_entry.unified_document

        # Display basic info
        self.stdout.write(self.style.SUCCESS("Basic Information:"))
        self.stdout.write(f"  Feed Entry ID:        {feed_entry.id}")
        if unified_doc:
            self.stdout.write(f"  Unified Document ID:  {unified_doc.id}")
            self.stdout.write(f"  Document Type:        {unified_doc.document_type}")
        else:
            self.stdout.write("  Unified Document ID:  None")
        self.stdout.write(f"  Content Type:         {feed_entry.content_type.model}")
        self.stdout.write(f"  Item ID:              {item.id}")

        title = getattr(item, "title", None) or getattr(
            item, "paper_title", f"Item #{item.id}"
        )
        self.stdout.write(f"  Title:                {title}")
        self.stdout.write(f"  Created:              {item.created_date}")
        self.stdout.write("")

        # Calculate scores
        try:
            v1_score = calculate_hot_score_for_item_DEPRECATED(feed_entry)
            v2_score = calculate_hot_score_for_item(feed_entry)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error calculating hot scores: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())
            return

        # Display scores
        self.stdout.write(self.style.SUCCESS("Hot Scores:"))
        self.stdout.write(f"  V1 Score (Old):       {v1_score:.2f}")
        self.stdout.write(f"  V2 Score (New):       {v2_score:.2f}")
        self.stdout.write(
            f"  Stored V1:            {feed_entry.hot_score or 'Not set'}"
        )
        self.stdout.write(
            f"  Stored V2:            {feed_entry.hot_score_v2 or 'Not set'}"
        )

        if v1_score > 0:
            change = v2_score - v1_score
            change_pct = change / v1_score * 100
            change_str = f"{change:+.2f} ({change_pct:+.1f}%)"
            self.stdout.write(f"  Change (V2-V1):       {change_str}")
        self.stdout.write("")

        # Get and display component breakdown
        if has_simulation:
            # Show both actual and simulated breakdowns
            self.stdout.write(self.style.SUCCESS("ACTUAL Component Breakdown (V2):"))
            self.stdout.write("")

            try:
                actual_components = self._get_components(item, unified_doc, feed_entry)
                self._display_detailed_components(actual_components)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error getting actual component breakdown: {e}")
                )
                import traceback

                self.stdout.write(traceback.format_exc())

            # Show simulation parameters being used
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("SIMULATION Parameters:"))
            self.stdout.write("")
            sim_active = []
            if sim_params.get("upvotes", 0) > 0:
                sim_active.append(f"  Upvotes:      {sim_params['upvotes']}")
            if sim_params.get("comments", 0) > 0:
                sim_active.append(f"  Comments:     {sim_params['comments']}")
            if sim_params.get("tips", 0) > 0:
                sim_active.append(f"  Tips:         {sim_params['tips']}")
            if sim_params.get("bounty", 0) > 0:
                sim_active.append(f"  Bounty:       {sim_params['bounty']}")
            if sim_params.get("urgent_bounty", False):
                sim_active.append("  Urgent Bounty: ENABLED")
            if sim_params.get("peer_reviews", 0) > 0:
                sim_active.append(f"  Peer Reviews: {sim_params['peer_reviews']}")
            if sim_params.get("altmetric", 0) > 0:
                sim_active.append(f"  Altmetric:    {sim_params['altmetric']}")
            if sim_params.get("age_hours", 0) > 0:
                sim_active.append(f"  Age (hours):  {sim_params['age_hours']}")

            for line in sim_active:
                self.stdout.write(line)
            self.stdout.write("")

            # Show simulated breakdown
            self.stdout.write(self.style.SUCCESS("SIMULATED Component Breakdown (V2):"))
            self.stdout.write("")

            try:
                sim_components = self._get_components_with_simulation(
                    item, unified_doc, feed_entry, sim_params
                )
                self._display_detailed_components(sim_components)

                # Calculate and display simulated score
                sim_score = self._calculate_score_from_components(sim_components)
                actual_score = self._calculate_score_from_components(actual_components)

                # Show comparison
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS("COMPARISON:"))
                self.stdout.write("")
                diff = sim_score - actual_score
                diff_pct = (diff / actual_score * 100) if actual_score > 0 else 0
                self.stdout.write(f"  Actual Score:    {actual_score:>8.0f}")
                self.stdout.write(f"  Simulated Score: {sim_score:>8.0f}")
                self.stdout.write(f"  Difference:      {diff:>8.0f} ({diff_pct:+.1f}%)")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error getting simulated component breakdown: {e}"
                    )
                )
                import traceback

                self.stdout.write(traceback.format_exc())
        else:
            # No simulation, show actual breakdown only
            self.stdout.write(self.style.SUCCESS("Component Breakdown (V2):"))
            self.stdout.write("")

            try:
                components = self._get_components(item, unified_doc, feed_entry)
                self._display_detailed_components(components)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error getting component breakdown: {e}")
                )
                import traceback

                self.stdout.write(traceback.format_exc())

    def _debug_unified_document(self, unified_document_id, sim_params=None):
        """Debug a specific unified document with detailed breakdown."""
        from researchhub_document.related_models.researchhub_unified_document_model import (  # noqa: E501
            ResearchhubUnifiedDocument,
        )

        # Check if any simulation parameters are active
        has_simulation = sim_params and any(
            [
                sim_params.get("upvotes", 0) > 0,
                sim_params.get("comments", 0) > 0,
                sim_params.get("tips", 0) > 0,
                sim_params.get("bounty", 0) > 0,
                sim_params.get("urgent_bounty", False),
                sim_params.get("peer_reviews", 0) > 0,
                sim_params.get("altmetric", 0) > 0,
                sim_params.get("age_hours", 0) > 0,
            ]
        )

        title_text = f"Debugging Unified Document ID: {unified_document_id}"
        if has_simulation:
            title_text += " (WITH SIMULATION)"
        self.stdout.write(self.style.SUCCESS(title_text))
        self.stdout.write("=" * 80)
        self.stdout.write("")

        try:
            unified_doc = ResearchhubUnifiedDocument.objects.get(id=unified_document_id)
        except ResearchhubUnifiedDocument.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f"Unified document with ID {unified_document_id} not found"
                )
            )
            return

        # Get the feed entry for this unified document
        try:
            feed_entry = (
                FeedEntry.objects.select_related("content_type")
                .prefetch_related("item")
                .get(unified_document=unified_doc)
            )
        except FeedEntry.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f"No feed entry found for unified document {unified_document_id}"
                )
            )
            return
        except FeedEntry.MultipleObjectsReturned:
            feed_entry = (
                FeedEntry.objects.select_related("content_type")
                .prefetch_related("item")
                .filter(unified_document=unified_doc)
                .first()
            )
            self.stdout.write(
                self.style.WARNING("Multiple feed entries found, using the first one")
            )

        item = feed_entry.item
        if not item:
            self.stdout.write(self.style.ERROR("Feed entry has no associated item"))
            return

        # Display basic info
        self.stdout.write(self.style.SUCCESS("Basic Information:"))
        self.stdout.write(f"  Feed Entry ID:        {feed_entry.id}")
        self.stdout.write(f"  Unified Document ID:  {unified_doc.id}")
        self.stdout.write(f"  Document Type:        {unified_doc.document_type}")
        self.stdout.write(f"  Content Type:         {feed_entry.content_type.model}")
        self.stdout.write(f"  Item ID:              {item.id}")

        title = getattr(item, "title", None) or getattr(
            item, "paper_title", f"Item #{item.id}"
        )
        self.stdout.write(f"  Title:                {title}")
        self.stdout.write(f"  Created:              {item.created_date}")
        self.stdout.write("")

        # Calculate scores
        try:
            v1_score = calculate_hot_score_for_item_DEPRECATED(feed_entry)
            v2_score = calculate_hot_score_for_item(feed_entry)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error calculating hot scores: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())
            return

        # Display scores
        self.stdout.write(self.style.SUCCESS("Hot Scores:"))
        self.stdout.write(f"  V1 Score (Old):       {v1_score:.2f}")
        self.stdout.write(f"  V2 Score (New):       {v2_score:.2f}")
        self.stdout.write(
            f"  Stored V1:            {feed_entry.hot_score or 'Not set'}"
        )
        self.stdout.write(
            f"  Stored V2:            {feed_entry.hot_score_v2 or 'Not set'}"
        )

        if v1_score > 0:
            change = v2_score - v1_score
            change_pct = change / v1_score * 100
            change_str = f"{change:+.2f} ({change_pct:+.1f}%)"
            self.stdout.write(f"  Change (V2-V1):       {change_str}")
        self.stdout.write("")

        # Get and display component breakdown
        if has_simulation:
            # Show both actual and simulated breakdowns
            self.stdout.write(self.style.SUCCESS("ACTUAL Component Breakdown (V2):"))
            self.stdout.write("")

            try:
                actual_components = self._get_components(item, unified_doc, feed_entry)
                self._display_detailed_components(actual_components)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error getting actual component breakdown: {e}")
                )
                import traceback

                self.stdout.write(traceback.format_exc())

            # Show simulation parameters being used
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("SIMULATION Parameters:"))
            self.stdout.write("")
            sim_active = []
            if sim_params.get("upvotes", 0) > 0:
                sim_active.append(f"  Upvotes:      {sim_params['upvotes']}")
            if sim_params.get("comments", 0) > 0:
                sim_active.append(f"  Comments:     {sim_params['comments']}")
            if sim_params.get("tips", 0) > 0:
                sim_active.append(f"  Tips:         {sim_params['tips']}")
            if sim_params.get("bounty", 0) > 0:
                sim_active.append(f"  Bounty:       {sim_params['bounty']}")
            if sim_params.get("urgent_bounty", False):
                sim_active.append("  Urgent Bounty: ENABLED")
            if sim_params.get("peer_reviews", 0) > 0:
                sim_active.append(f"  Peer Reviews: {sim_params['peer_reviews']}")
            if sim_params.get("altmetric", 0) > 0:
                sim_active.append(f"  Altmetric:    {sim_params['altmetric']}")
            if sim_params.get("age_hours", 0) > 0:
                sim_active.append(f"  Age (hours):  {sim_params['age_hours']}")

            for line in sim_active:
                self.stdout.write(line)
            self.stdout.write("")

            # Show simulated breakdown
            self.stdout.write(self.style.SUCCESS("SIMULATED Component Breakdown (V2):"))
            self.stdout.write("")

            try:
                sim_components = self._get_components_with_simulation(
                    item, unified_doc, feed_entry, sim_params
                )
                self._display_detailed_components(sim_components)

                # Calculate and display simulated score
                sim_score = self._calculate_score_from_components(sim_components)
                actual_score = self._calculate_score_from_components(actual_components)

                # Show comparison
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS("COMPARISON:"))
                self.stdout.write("")
                diff = sim_score - actual_score
                diff_pct = (diff / actual_score * 100) if actual_score > 0 else 0
                self.stdout.write(f"  Actual Score:    {actual_score:>8.0f}")
                self.stdout.write(f"  Simulated Score: {sim_score:>8.0f}")
                self.stdout.write(f"  Difference:      {diff:>8.0f} ({diff_pct:+.1f}%)")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error getting simulated component breakdown: {e}"
                    )
                )
                import traceback

                self.stdout.write(traceback.format_exc())
        else:
            # No simulation, show actual breakdown only
            self.stdout.write(self.style.SUCCESS("Component Breakdown (V2):"))
            self.stdout.write("")

            try:
                components = self._get_components(item, unified_doc, feed_entry)
                self._display_detailed_components(components)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error getting component breakdown: {e}")
                )
                import traceback

                self.stdout.write(traceback.format_exc())

    def _calculate_score_from_components(self, components):
        """Calculate final hot score from component breakdown."""
        raw_score = components["engagement_score"] / components["time_denominator"]
        scaled_score = raw_score * 100
        return max(0, int(scaled_score))

    def _display_detailed_components(self, components):
        """Display detailed component breakdown for debugging."""
        # Signal breakdown
        self.stdout.write("  Signal Components:")
        self.stdout.write(
            f"    Altmetric:        Raw={components['altmetric']['raw']:>8.1f}  "
            f"→  Component={components['altmetric']['component']:>8.2f}"
        )

        bounty_marker = " ⚠️  URGENT!" if components["bounty"]["urgent"] else ""
        self.stdout.write(
            f"    Bounty:           Raw={components['bounty']['raw']:>8.1f}  "
            f"→  Component={components['bounty']['component']:>8.2f}{bounty_marker}"
        )

        self.stdout.write(
            f"    Tips/Boosts:      Raw={components['tip']['raw']:>8.1f}  "
            f"→  Component={components['tip']['component']:>8.2f}"
        )

        self.stdout.write(
            f"    Peer Reviews:     Raw={components['peer_review']['raw']:>8.0f}  "
            f"→  Component={components['peer_review']['component']:>8.2f}"
        )

        self.stdout.write(
            f"    Upvotes:          Raw={components['upvote']['raw']:>8.0f}  "
            f"→  Component={components['upvote']['component']:>8.2f}"
        )

        self.stdout.write(
            f"    Comments:         Raw={components['comment']['raw']:>8.0f}  "
            f"→  Component={components['comment']['component']:>8.2f}"
        )

        self.stdout.write("")

        # Time decay breakdown
        self.stdout.write("  Time Decay:")
        self.stdout.write(f"    Age (hours):      {components['age_hours']:>8.1f}")
        self.stdout.write(
            f"    Freshness Mult:   {components['freshness_multiplier']:>8.2f}"
        )
        self.stdout.write("")

        # Final calculation
        self.stdout.write("  Final Calculation:")
        self.stdout.write(
            f"    Engagement Score: {components['engagement_score']:>8.2f}"
        )
        self.stdout.write(
            f"    Time Denominator: {components['time_denominator']:>8.2f}"
        )
        self.stdout.write("")

        raw_score = components["engagement_score"] / components["time_denominator"]
        scaled_score = raw_score * 100
        final_score = max(0, int(scaled_score))  # Apply same logic as hot_score.py
        eng_score = components["engagement_score"]
        time_denom = components["time_denominator"]
        self.stdout.write(
            f"    Raw Score:        {raw_score:>8.4f}  "
            f"({eng_score:.2f} / {time_denom:.2f})"
        )
        self.stdout.write(
            f"    Scaled (×100):    {scaled_score:>8.2f}  " "(preserves precision)"
        )
        self.stdout.write(
            f"    Final Score:      {final_score:>8.0f}  " "(integer, min=0)"
        )
        self.stdout.write("")

        # Config info
        self.stdout.write("  Configuration Used:")
        config = HOT_SCORE_CONFIG
        self.stdout.write(f"    Gravity:          {config['time_decay']['gravity']}")
        self.stdout.write(f"    Base Hours:       {config['time_decay']['base_hours']}")
        self.stdout.write("    Signal Weights:")
        for signal_name, signal_config in config["signals"].items():
            weight = signal_config["weight"]
            log_base = signal_config["log_base"]
            self.stdout.write(
                f"      {signal_name:15s} weight={weight:>5.1f}  "
                f"log_base={log_base}"
            )
