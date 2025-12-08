"""
Management command to generate the Bedrock prompt for manual testing.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from paper.models import Figure, Paper
from paper.services.bedrock_primary_image_service import BedrockPrimaryImageService


class Command(BaseCommand):
    help = "Generate Bedrock prompt for manual testing (copy/paste into AWS Console)"

    def add_arguments(self, parser):
        parser.add_argument(
            "paper_id",
            type=int,
            help="Paper ID to generate prompt for",
        )
        parser.add_argument(
            "--output-file",
            type=str,
            help="Save prompt to JSON file (optional)",
        )

    def handle(self, *args, **options):
        paper_id = options["paper_id"]

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} does not exist")

        figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE)

        if not figures.exists():
            raise CommandError(
                f"Paper {paper_id} has no extracted figures. "
                "Run extract_figures_for_paper first."
            )

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("BEDROCK PROMPT GENERATOR")
        self.stdout.write("=" * 60 + "\n")

        self.stdout.write(f"Paper ID: {paper.id}")
        self.stdout.write(f"Title: {paper.title}")
        self.stdout.write(f"Abstract: {(paper.abstract or '')[:200]}...")
        self.stdout.write(f"Figures: {figures.count()}\n")

        # Generate the prompt using the service
        service = BedrockPrimaryImageService()

        # Build the request body
        system_prompt = (
            "You are an expert scientific figure evaluator specializing in "
            "selecting the most appropriate primary images for research papers. "
            "You understand scientific visualization, data presentation, and "
            "what makes a figure suitable for public display in research feeds."
        )

        prompt_text = service._build_prompt(
            paper.title or "",
            paper.abstract or "",
            figures.count(),
        )

        user_content = []
        user_content.append({"type": "text", "text": prompt_text})

        # Add figures (but we'll show them as placeholders for manual entry)
        figure_info = []
        for idx, figure in enumerate(figures):
            encoded_result = service._encode_image_to_base64(figure)
            if encoded_result is None:
                self.stdout.write(
                    self.style.WARNING(f"  ⚠ Skipping figure {idx} - encoding failed")
                )
                continue

            base64_image, media_type = encoded_result
            figure_info.append(
                {
                    "index": idx,
                    "filename": figure.file.name,
                    "size": figure.file.size,
                    "media_type": media_type,
                }
            )

            user_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_image[:100] + "...[truncated for display]",
                    },
                }
            )

            user_content.append({"type": "text", "text": f"Figure {idx}"})

        # Display information
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("PROMPT INFORMATION")
        self.stdout.write("=" * 60 + "\n")

        self.stdout.write(f"Model ID: {service.model_id}")
        self.stdout.write(f"System Prompt Length: {len(system_prompt)} chars")
        self.stdout.write(f"User Prompt Length: {len(prompt_text)} chars")
        self.stdout.write(f"Number of Figures: {len(figure_info)}\n")

        self.stdout.write("Figure Details:")
        for fig_info in figure_info:
            self.stdout.write(
                f"  Figure {fig_info['index']}: {fig_info['filename']} "
                f"({fig_info['size']} bytes, {fig_info['media_type']})"
            )

        # Save full request to file
        output_file = options.get("output_file")
        if output_file:
            # Create a version with full base64 data for actual use
            full_request = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": user_content,
                    }
                ],
            }

            # Replace truncated images with full data
            # Image blocks are at indices 1, 3, 5, 7...
            # (each figure takes 2 slots: image + text label)
            figure_idx = 0
            content_list = full_request["messages"][0]["content"]
            for content_idx, content_item in enumerate(content_list):
                is_image = content_item.get("type") == "image"
                has_more_figures = figure_idx < len(figure_info)
                if is_image and has_more_figures:
                    fig_info = figure_info[figure_idx]
                    encoded_result = service._encode_image_to_base64(
                        figures[fig_info["index"]]
                    )
                    if encoded_result:
                        base64_image, media_type = encoded_result
                        content_list[content_idx]["source"]["data"] = base64_image
                    figure_idx += 1

            with open(output_file, "w") as f:
                json.dump(full_request, f, indent=2)

            self.stdout.write(f"\n✓ Full request saved to: {output_file}")

        # Display prompt text for manual entry
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("PROMPT TEXT (for manual entry)")
        self.stdout.write("=" * 60 + "\n")
        self.stdout.write(prompt_text)

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("NEXT STEPS")
        self.stdout.write("=" * 60 + "\n")
        self.stdout.write(
            "1. Copy the prompt text above\n"
            "2. Go to AWS Bedrock Console → Playground\n"
            "3. Select model: anthropic.claude-3-haiku-20240307-v1:0\n"
            "4. Paste the prompt and add your figures\n"
            "5. Get the JSON response\n"
            "6. Use 'process_bedrock_response' command with the response\n"
        )

        self.stdout.write("\n" + "=" * 60)
