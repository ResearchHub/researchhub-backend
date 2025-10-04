"""
Identify potentially low-quality hubs using various heuristics.
"""

import re
from collections import defaultdict

from django.core.management.base import BaseCommand

from hub.models import Hub


class Command(BaseCommand):
    help = "Identify potentially low-quality hubs based on various quality signals"

    def add_arguments(self, parser):
        parser.add_argument(
            "--namespace",
            type=str,
            help=(
                "Filter by namespace (e.g., 'journal'). "
                "If not specified, checks all hubs."
            ),
        )
        parser.add_argument(
            "--min-score",
            type=int,
            default=2,
            help=(
                "Minimum quality score to flag as low-quality (default: 2). "
                "Higher values = stricter filtering. Score = number of issues found."
            ),
        )
        parser.add_argument(
            "--output-file",
            type=str,
            help="Save results to a file instead of stdout",
        )
        parser.add_argument(
            "--show-all",
            action="store_true",
            help="Show all hubs, not just potentially low-quality ones",
        )
        parser.add_argument(
            "--checks",
            type=str,
            help=(
                "Comma-separated list of checks to run. "
                "Available: test, numeric_suffix, short_name, non_ascii, "
                "inactive, no_papers, unusual_chars, all_numeric, duplicate_keywords. "
                "If not specified, all checks will run."
            ),
        )

    def handle(self, *args, **options):
        namespace = options.get("namespace")
        min_score = options.get("min_score", 2)
        output_file = options.get("output_file")
        show_all = options.get("show_all", False)

        # Parse which checks to run
        checks_arg = options.get("checks")
        if checks_arg:
            self.checks_to_run = set(
                check.strip() for check in checks_arg.split(",") if check.strip()
            )
            available_checks = {
                "test",
                "numeric_suffix",
                "short_name",
                "non_ascii",
                "inactive",
                "no_papers",
                "unusual_chars",
                "all_numeric",
                "duplicate_keywords",
            }
            invalid_checks = self.checks_to_run - available_checks
            if invalid_checks:
                self.stdout.write(
                    self.style.ERROR(
                        f"Invalid checks: {', '.join(invalid_checks)}. "
                        f"Available: {', '.join(sorted(available_checks))}"
                    )
                )
                return
            self.stdout.write(
                self.style.WARNING(
                    f"Running only selected checks: "
                    f"{', '.join(sorted(self.checks_to_run))}\n"
                )
            )
        else:
            self.checks_to_run = None  # Run all checks

        self.stdout.write(self.style.SUCCESS("Analyzing hubs for quality issues...\n"))

        # Build queryset
        queryset = Hub.objects.all()
        if namespace:
            queryset = queryset.filter(namespace=namespace)
            self.stdout.write(
                self.style.WARNING(f"Filtering by namespace: {namespace}\n")
            )

        total_hubs = queryset.count()
        self.stdout.write(f"Total hubs to analyze: {total_hubs}\n")

        # Analyze all hubs
        low_quality_hubs = []

        for hub in queryset.order_by("id"):
            issues = self._analyze_hub(hub)
            quality_score = len(issues)

            if quality_score >= min_score or show_all:
                low_quality_hubs.append(
                    {
                        "hub": hub,
                        "issues": issues,
                        "score": quality_score,
                    }
                )

        # Sort by quality score (worst first)
        low_quality_hubs.sort(key=lambda x: x["score"], reverse=True)

        # Display or save results
        if output_file:
            self._save_to_file(low_quality_hubs, output_file, total_hubs, min_score)
        else:
            self._display_results(low_quality_hubs, total_hubs, min_score)

    def _analyze_hub(self, hub):
        """
        Analyze a hub and return a list of quality issues.

        Returns a list of issue descriptions.
        """
        issues = []

        # Check 1: Test/dummy hubs
        if self._should_run_check("test") and self._is_test_hub(hub):
            issues.append("Contains 'test' keyword")

        # Check 2: Has numeric suffix (potential duplicate)
        if self._should_run_check("numeric_suffix") and self._has_numeric_suffix(hub):
            issues.append(f"Has numeric suffix in slug: {hub.slug}")

        # Check 3: Very short name (1-2 characters)
        if self._should_run_check("short_name") and self._is_very_short_name(hub):
            issues.append(f"Very short name ({len(hub.name)} chars)")

        # Check 4: Has non-ASCII characters (might be non-English)
        if self._should_run_check("non_ascii"):
            non_ascii_chars = self._get_non_ascii_chars(hub)
            if non_ascii_chars:
                issues.append(
                    f"Contains non-ASCII characters: {', '.join(non_ascii_chars)}"
                )

        # Check 5: No activity (strict: no papers, subscribers, or documents)
        if self._should_run_check("inactive") and self._is_inactive(hub):
            issues.append(
                f"Inactive (papers: {hub.paper_count}, "
                f"subscribers: {hub.subscriber_count}, "
                f"documents: {hub.related_documents.count()})"
            )

        # Check 6: No papers (regardless of subscribers)
        if self._should_run_check("no_papers") and self._has_no_papers(hub):
            issues.append(f"No papers (paper_count: {hub.paper_count})")

        # Check 7: Special characters in name (unusual)
        if self._should_run_check("unusual_chars") and self._has_unusual_characters(
            hub
        ):
            issues.append("Contains unusual special characters")

        # Check 8: All numeric name
        if self._should_run_check("all_numeric") and self._is_all_numeric(hub):
            issues.append("Name is all numbers")

        # Check 9: Duplicate-like patterns
        if self._should_run_check("duplicate_keywords"):
            duplicate_pattern = self._check_duplicate_patterns(hub)
            if duplicate_pattern:
                issues.append(duplicate_pattern)

        return issues

    def _should_run_check(self, check_name):
        """Check if a specific quality check should run"""
        if self.checks_to_run is None:
            return True  # Run all checks
        return check_name in self.checks_to_run

    def _is_test_hub(self, hub):
        """Check if hub appears to be a test/dummy hub"""
        test_keywords = ["test", "dummy", "sample", "example", "placeholder"]
        name_lower = hub.name.lower()
        return any(keyword in name_lower for keyword in test_keywords)

    def _has_numeric_suffix(self, hub):
        """Check if hub has numeric suffix like 'nature-1', 'cell-2'"""
        if not hub.slug:
            return False
        return bool(re.search(r"-\d+$", hub.slug))

    def _is_very_short_name(self, hub):
        """Check if hub name is suspiciously short (1-2 characters)"""
        return len(hub.name.strip()) <= 2

    def _get_non_ascii_chars(self, hub):
        """
        Get list of non-ASCII characters in hub name.

        Returns a list of unique non-ASCII characters with their descriptions.
        """
        non_ascii_chars = set()

        for char in hub.name:
            if ord(char) > 127:  # ASCII range is 0-127
                # Create description with character and unicode name
                try:
                    import unicodedata

                    char_name = unicodedata.name(char, "UNKNOWN")
                    # Simplify common cases
                    if "DASH" in char_name:
                        desc = f"'{char}' (dash/hyphen variant)"
                    elif "QUOTE" in char_name or "APOSTROPHE" in char_name:
                        desc = f"'{char}' (quote variant)"
                    elif "SPACE" in char_name:
                        desc = f"'{char}' (space variant)"
                    else:
                        desc = f"'{char}' ({char_name})"
                    non_ascii_chars.add(desc)
                except Exception:
                    non_ascii_chars.add(f"'{char}' (U+{ord(char):04X})")

        return sorted(non_ascii_chars)

    def _is_inactive(self, hub):
        """
        Check if hub is truly inactive.

        Only flags hubs that have:
        - 0 papers AND 0 subscribers AND 0 documents AND not recently created
        """
        # Don't flag recently created hubs (within last 30 days)
        from datetime import timedelta

        from django.utils import timezone

        thirty_days_ago = timezone.now() - timedelta(days=30)
        is_recent = hub.created_date > thirty_days_ago

        if is_recent:
            return False

        # Check if truly inactive (no content at all)
        has_no_papers = hub.paper_count == 0
        has_no_subscribers = hub.subscriber_count == 0
        has_no_documents = hub.related_documents.count() == 0

        return has_no_papers and has_no_subscribers and has_no_documents

    def _has_no_papers(self, hub):
        """
        Check if hub has no papers.

        This is a lighter check than _is_inactive - useful for finding
        hubs that might be unused even if they have subscribers.
        """
        return hub.paper_count == 0

    def _has_unusual_characters(self, hub):
        """
        Check for unusual special characters (not standard punctuation).

        Allows common characters found in legitimate hub names including:
        - Letters, numbers, spaces
        - Hyphens, underscores, apostrophes
        - Periods, commas, colons, semicolons
        - Parentheses, brackets, braces
        - Ampersands, slashes, pipes
        - Plus, equals, percent, dollar, at signs
        """
        # Allow a wide range of common characters
        # Only flag truly unusual characters like control chars, emojis, etc.
        allowed_pattern = (
            r"^[a-zA-Z0-9"  # Letters and numbers
            r"\s"  # Whitespace
            r"\-\_"  # Hyphen, underscore
            r"\'\"\`"  # Quotes
            r"\.\,\:\;\!\?"  # Punctuation
            r"\(\)\[\]\{\}"  # Brackets
            r"\&\@\#\$\%"  # Symbols
            r"\/\\\|\~\+\=\*"  # More symbols
            r"]+$"
        )
        return not bool(re.match(allowed_pattern, hub.name))

    def _is_all_numeric(self, hub):
        """Check if name is entirely numeric"""
        return hub.name.strip().isdigit()

    def _check_duplicate_patterns(self, hub):
        """Check for patterns that suggest this might be a duplicate"""
        name = hub.name.lower().strip()

        # Check for "copy", "duplicate", etc.
        duplicate_keywords = ["copy", "duplicate", "dup", "old", "new", "backup"]
        for keyword in duplicate_keywords:
            if keyword in name:
                return f"Contains duplicate keyword: '{keyword}'"

        return None

    def _find_plural_singular_pairs(self, queryset):
        """
        Identify potential plural/singular pairs.

        This is done as a separate analysis across all hubs.
        """
        # Common plural patterns
        pairs = []
        names_by_root = defaultdict(list)

        for hub in queryset:
            name = hub.name.lower().strip()

            # Try to find root by removing common plural endings
            roots = [name]

            # Pattern 1: ends with 's' -> remove it
            if name.endswith("s") and len(name) > 2:
                roots.append(name[:-1])

            # Pattern 2: ends with 'es' -> remove them
            if name.endswith("es") and len(name) > 3:
                roots.append(name[:-2])

            # Pattern 3: ends with 'ies' -> replace with 'y'
            if name.endswith("ies") and len(name) > 4:
                roots.append(name[:-3] + "y")

            for root in roots:
                names_by_root[root].append(hub)

        # Find roots with multiple hubs
        for root, hubs in names_by_root.items():
            if len(hubs) > 1:
                pairs.append((root, hubs))

        return pairs

    def _display_results(self, low_quality_hubs, total_hubs, min_score):
        """Display results to stdout"""
        self.stdout.write("=" * 80)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nFound {len(low_quality_hubs)} potentially low-quality hubs "
                f"(out of {total_hubs} total)\n"
            )
        )

        if not low_quality_hubs:
            self.stdout.write(self.style.SUCCESS("No low-quality hubs found! 🎉"))
            return

        # Group by quality score
        by_score = defaultdict(list)
        for item in low_quality_hubs:
            by_score[item["score"]].append(item)

        for score in sorted(by_score.keys(), reverse=True):
            hubs = by_score[score]
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(
                self.style.ERROR(f"\n🚩 Quality Score: {score} ({len(hubs)} hubs)\n")
            )

            for item in hubs:
                hub = item["hub"]
                issues = item["issues"]

                self.stdout.write(f"\nHub: {hub.name}")
                self.stdout.write(f"  ID: {hub.id}")
                self.stdout.write(f"  Slug: {hub.slug}")
                self.stdout.write(f"  Namespace: {hub.namespace or 'None'}")
                self.stdout.write(f"  Paper Count: {hub.paper_count}")
                self.stdout.write(f"  Subscriber Count: {hub.subscriber_count}")
                self.stdout.write(f"  Created: {hub.created_date}")
                self.stdout.write(self.style.WARNING("  Issues:"))
                for issue in issues:
                    self.stdout.write(f"    • {issue}")

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("\n📊 Summary by Issue Type:\n"))

        issue_counts = defaultdict(int)
        for item in low_quality_hubs:
            for issue in item["issues"]:
                # Extract issue type (first part before details)
                issue_type = issue.split("(")[0].split(":")[0].strip()
                issue_counts[issue_type] += 1

        for issue_type, count in sorted(
            issue_counts.items(), key=lambda x: x[1], reverse=True
        ):
            self.stdout.write(f"  {issue_type}: {count} hubs")

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.WARNING(
                "\n💡 To remove these hubs, use the bulk-remove-hubs command:"
            )
        )
        self.stdout.write(
            '   python manage.py bulk-remove-hubs --hub-ids "<comma-separated-ids>"'
        )

    def _save_to_file(self, low_quality_hubs, filepath, total_hubs, min_score):
        """Save results to a file"""
        with open(filepath, "w") as f:
            f.write("# Low Quality Hubs Analysis\n")
            f.write(f"# Generated: {self._get_timestamp()}\n")
            f.write(f"# Total hubs analyzed: {total_hubs}\n")
            f.write(f"# Low quality hubs found: {len(low_quality_hubs)}\n")
            f.write(f"# Minimum quality score: {min_score}\n")
            f.write("\n")

            # Group by score
            by_score = defaultdict(list)
            for item in low_quality_hubs:
                by_score[item["score"]].append(item)

            for score in sorted(by_score.keys(), reverse=True):
                hubs = by_score[score]
                f.write(f"\n{'=' * 80}\n")
                f.write(f"Quality Score: {score} ({len(hubs)} hubs)\n")
                f.write(f"{'=' * 80}\n\n")

                for item in hubs:
                    hub = item["hub"]
                    issues = item["issues"]

                    f.write(f"Hub: {hub.name}\n")
                    f.write(f"  ID: {hub.id}\n")
                    f.write(f"  Slug: {hub.slug}\n")
                    f.write(f"  Namespace: {hub.namespace or 'None'}\n")
                    f.write(f"  Paper Count: {hub.paper_count}\n")
                    f.write(f"  Subscriber Count: {hub.subscriber_count}\n")
                    f.write(f"  Created: {hub.created_date}\n")
                    f.write("  Issues:\n")
                    for issue in issues:
                        f.write(f"    • {issue}\n")
                    f.write("\n")

            # Hub IDs for easy removal
            f.write("\n" + "=" * 80 + "\n")
            f.write("# Hub IDs for bulk removal\n")
            f.write("# (Copy these to use with bulk-remove-hubs --hub-ids-file)\n")
            f.write("=" * 80 + "\n\n")

            for item in low_quality_hubs:
                f.write(f"{item['hub'].id}\n")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Analysis saved to {filepath}\n"
                f"  Found {len(low_quality_hubs)} low-quality hubs"
            )
        )

    def _get_timestamp(self):
        """Get current timestamp for file headers"""
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
