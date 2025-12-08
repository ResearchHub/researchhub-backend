"""
Management command to process a Bedrock response and mark primary image.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from paper.models import Figure, Paper


class Command(BaseCommand):
    help = "Process Bedrock response JSON and mark primary image in database"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            help="Paper ID to process response for",
        )
        parser.add_argument(
            "--response-file",
            type=str,
            help="Path to JSON file containing Bedrock response",
        )
        parser.add_argument(
            "--response-json",
            type=str,
            help="Bedrock response JSON as string (alternative to --response-file)",
        )

    def handle(self, *args, **options):
        paper_id = options["paper_id"]

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} does not exist")

        figures = Figure.objects.filter(
            paper=paper, figure_type=Figure.FIGURE
        ).order_by("created_date")

        if not figures.exists():
            raise CommandError(
                f"Paper {paper_id} has no extracted figures. "
                "Run extract_figures_for_paper first."
            )

        # Load response
        response_data = self._load_response(options)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("PROCESSING BEDROCK RESPONSE")
        self.stdout.write("=" * 60 + "\n")

        self.stdout.write(f"Paper ID: {paper.id}")
        self.stdout.write(f"Title: {paper.title}")
        self.stdout.write(f"Available Figures: {figures.count()}\n")

        # Parse response
        selected_index = self._parse_response(response_data, figures.count())

        if selected_index is None:
            raise CommandError("Failed to parse response. Check response format.")

        # Validate index
        if selected_index < 0 or selected_index >= figures.count():
            raise CommandError(
                f"Invalid figure index {selected_index}. "
                f"Must be between 0 and {figures.count() - 1}"
            )

        # Get selected figure
        selected_figure = figures[selected_index]

        self.stdout.write(f"\nSelected Figure Index: {selected_index}")
        self.stdout.write(f"Selected Figure: {selected_figure.file.name}")

        # Check score threshold
        from paper.constants.figure_selection_criteria import (
            MIN_PRIMARY_SCORE_THRESHOLD,
        )

        best_score = None
        scores = response_data.get("scores", {})
        figure_key = f"figure_{selected_index}"
        if figure_key in scores and "total_score" in scores[figure_key]:
            best_score = scores[figure_key]["total_score"]

        should_use_preview = False
        if best_score is not None and best_score < MIN_PRIMARY_SCORE_THRESHOLD:
            should_use_preview = True
            self.stdout.write(
                self.style.WARNING(
                    f"\nScore {best_score}% is below threshold "
                    f"{MIN_PRIMARY_SCORE_THRESHOLD}%"
                )
            )
            self.stdout.write("Will create preview instead...")

        if should_use_preview:
            from paper.tasks import _create_pdf_screenshot

            preview_created = _create_pdf_screenshot(paper)
            if preview_created:
                self.stdout.write(
                    self.style.SUCCESS("\n✓ Created preview as primary image")
                )
                # Show scores before returning
                if isinstance(response_data, dict) and "scores" in response_data:
                    self.stdout.write("\n" + "-" * 60)
                    self.stdout.write("SCORES (figure was below threshold):")
                    self.stdout.write("-" * 60)
                    scores = response_data.get("scores", {})
                    figure_key = f"figure_{selected_index}"
                    if figure_key in scores:
                        for criterion, score in scores[figure_key].items():
                            if criterion != "total_score":
                                self.stdout.write(f"  {criterion}: {score}")
                        if "total_score" in scores[figure_key]:
                            self.stdout.write(
                                f"\n  Total Score: {scores[figure_key]['total_score']}% "
                                f"(threshold: {MIN_PRIMARY_SCORE_THRESHOLD}%)"
                            )
                return
            else:
                raise CommandError("Failed to create preview")
        else:
            # Update database
            self.stdout.write("\nUpdating database...")

            # Clear existing primary flags
            Figure.objects.filter(paper=paper).update(is_primary=False)

            # Set new primary
            selected_figure.is_primary = True
            selected_figure.save(update_fields=["is_primary"])

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Primary image set: {selected_figure.file.name}"
                )
            )

        # Show scores if available
        if isinstance(response_data, dict) and "scores" in response_data:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write("SCORES (if available):")
            self.stdout.write("-" * 60)
            scores = response_data.get("scores", {})
            figure_key = f"figure_{selected_index}"
            if figure_key in scores:
                for criterion, score in scores[figure_key].items():
                    if criterion != "total_score":
                        self.stdout.write(f"  {criterion}: {score}")
                if "total_score" in scores[figure_key]:
                    self.stdout.write(
                        f"\n  Total Score: {scores[figure_key]['total_score']}"
                    )

        # Show reasoning if available
        if isinstance(response_data, dict) and "reasoning" in response_data:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write("REASONING:")
            self.stdout.write("-" * 60)
            self.stdout.write(f"  {response_data['reasoning']}")

        self.stdout.write("\n" + "=" * 60)

    def _load_response(self, options):
        """Load response from file or JSON string."""
        if options.get("response_file"):
            try:
                with open(options["response_file"], "r") as f:
                    return json.load(f)
            except FileNotFoundError:
                raise CommandError(
                    f"Response file not found: {options['response_file']}"
                )
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid JSON in file: {e}")

        elif options.get("response_json"):
            try:
                return json.loads(options["response_json"])
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid JSON string: {e}")
        else:
            raise CommandError("Must provide either --response-file or --response-json")

    def _parse_response(self, response_data, num_figures):
        """
        Parse Bedrock response to extract selected figure index.

        Handles different response formats:
        1. Direct JSON object with selected_figure_index
        2. Bedrock API response format with content blocks
        3. Text response containing JSON
        """
        # If it's a Bedrock API response format
        if isinstance(response_data, dict) and "content" in response_data:
            # Extract text from content blocks
            text_content = ""
            for content_block in response_data["content"]:
                if content_block.get("type") == "text":
                    text_content += content_block.get("text", "")
            response_data = self._extract_json_from_text(text_content)

        # If it's a string, try to parse as JSON
        if isinstance(response_data, str):
            response_data = self._extract_json_from_text(response_data)

        # Now response_data should be a dict
        if not isinstance(response_data, dict):
            self.stdout.write(
                self.style.ERROR(f"Unexpected response format: {type(response_data)}")
            )
            return None

        # Try to get selected_figure_index
        selected_index = response_data.get("selected_figure_index")

        if selected_index is None:
            # Try alternative field names
            selected_index = response_data.get("selected_index")
            if selected_index is None:
                selected_index = response_data.get("figure_index")

        return selected_index

    def _extract_json_from_text(self, text):
        """Extract JSON object from text (handles markdown code blocks)."""
        # Try to find JSON in markdown code blocks
        if "```json" in text:
            json_start = text.find("```json") + 7
            json_end = text.find("```", json_start)
            json_text = text[json_start:json_end].strip()
        elif "```" in text:
            json_start = text.find("```") + 3
            json_end = text.find("```", json_start)
            json_text = text[json_start:json_end].strip()
        else:
            # Try to find JSON object
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_text = text[json_start:json_end]
            else:
                raise ValueError("No JSON found in text")

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            # If parsing fails, return the text as-is
            return text
