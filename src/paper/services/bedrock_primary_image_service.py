import base64
import logging
from io import BytesIO
from typing import List, Optional, Tuple

from django.conf import settings
from PIL import Image

from utils import sentry
from utils.aws import create_client

logger = logging.getLogger(__name__)

MAX_IMAGES_PER_BEDROCK_REQUEST = 20

BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"

# Figure selection criteria weights
ASPECT_RATIO_MATCH_WEIGHT = 8
SCIENTIFIC_IMPACT_WEIGHT = 18
VISUAL_QUALITY_WEIGHT = 18
DATA_DENSITY_WEIGHT = 8
NARRATIVE_CONTEXT_WEIGHT = 18
INTERPRETABILITY_WEIGHT = 12
UNIQUENESS_WEIGHT = 5
SOCIAL_MEDIA_POTENTIAL_WEIGHT = 20

# If the best figure scores below this, we'll use a preview instead
MIN_PRIMARY_SCORE_THRESHOLD = 70

CRITERIA_DESCRIPTIONS = {
    "aspect_ratio_match": {
        "weight": ASPECT_RATIO_MATCH_WEIGHT,
        "description": ("Compatibility with standard feed dimensions (16:9, 4:3, 1:1)"),
        "key_metrics": "Distance from ideal ratio",
    },
    "scientific_impact": {
        "weight": SCIENTIFIC_IMPACT_WEIGHT,
        "description": (
            "Presents primary findings, conclusions, or key methods of " "the paper"
        ),
        "key_metrics": (
            "Central vs supporting result, methods figures " "(e.g., imaging, staining)"
        ),
    },
    "visual_quality": {
        "weight": VISUAL_QUALITY_WEIGHT,
        "description": (
            "Clarity, resolution, color fidelity, professional appearance, "
            "readability"
        ),
        "key_metrics": (
            "DPI, color depth, artifacts, text size and legibility, contrast"
        ),
    },
    "data_density": {
        "weight": DATA_DENSITY_WEIGHT,
        "description": "Information richness vs white space ratio",
        "key_metrics": "Dimensions, number of curves/plots",
    },
    "narrative_context": {
        "weight": NARRATIVE_CONTEXT_WEIGHT,
        "description": (
            "Ability to serve as paper introduction, overview, or summary " "figure"
        ),
        "key_metrics": (
            "Structural overview vs detail, provides context for the paper"
        ),
    },
    "interpretability": {
        "weight": INTERPRETABILITY_WEIGHT,
        "description": (
            "Self-explanatory legends, labels, intuitive presentation, " "readability"
        ),
        "key_metrics": ("Axis labels, color coding clarity, text size and legibility"),
    },
    "uniqueness": {
        "weight": UNIQUENESS_WEIGHT,
        "description": "Data or analysis specific to this paper",
        "key_metrics": "Appears in other papers",
    },
    "social_media_potential": {
        "weight": SOCIAL_MEDIA_POTENTIAL_WEIGHT,
        "description": (
            "Visual appeal, eye-catching quality for Twitter/Instagram/"
            "LinkedIn sharing"
        ),
        "key_metrics": ("Visual interest, discovery-worthy, stands out, color appeal"),
    },
}


class BedrockPrimaryImageService:
    """Service for selecting primary image using AWS Bedrock."""

    def __init__(self):
        self.bedrock_client = create_client(
            "bedrock-runtime", region_name=settings.AWS_REGION_NAME
        )
        self.model_id = BEDROCK_MODEL_ID
        self.anthropic_version = BEDROCK_ANTHROPIC_VERSION

    def _encode_image_to_base64(self, figure) -> Optional[tuple]:
        """
        Encode figure image to base64 string.

        Resizes and compresses image to fit within Bedrock's limits before encoding.

        Args:
            figure: Figure model instance

        Returns:
            Tuple of (base64_image_string, media_type) or None if encoding fails
        """
        try:
            if not figure.file:
                return None

            figure.file.open("rb")
            image_bytes = figure.file.read()
            figure.file.close()

            image_bytes = self._resize_and_compress_for_bedrock(image_bytes, figure.id)
            base64_image = base64.b64encode(image_bytes).decode("utf-8")

            return base64_image, "image/jpeg"

        except Exception as e:
            logger.error(f"Error encoding figure {figure.id} to base64: {e}")
            return None

    def _resize_and_compress_for_bedrock(
        self,
        image_data: bytes,
        figure_id: int,
        max_dimension: int = 8000,
        max_file_size_mb: float = 4.5,
    ) -> bytes:
        """
        Resize and compress image to fit within Bedrock's limits.
        """
        max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)

        image = Image.open(BytesIO(image_data))

        # Step 1: Resize dimensions if needed
        width, height = image.size
        if width > max_dimension or height > max_dimension:
            logger.warning(
                f"Figure {figure_id} exceeds dimension limit "
                f"({width}x{height}), resizing to {max_dimension}px"
            )
            if width > height:
                new_width = max_dimension
                new_height = int((height * max_dimension) / width)
            else:
                new_height = max_dimension
                new_width = int((width * max_dimension) / height)

            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Step 2: Compress until file size is acceptable
        quality = 95
        while quality > 10:
            output_buffer = BytesIO()
            image.save(output_buffer, format="JPEG", quality=quality, optimize=True)

            file_size = output_buffer.tell()

            if file_size <= max_file_size_bytes:
                return output_buffer.getvalue()

            # Reduce quality for next iteration
            quality -= 10

        # If still too large, resize further
        scale_factor = 0.9
        while quality <= 10:
            # Reduce image dimensions
            new_width = int(image.width * scale_factor)
            new_height = int(image.height * scale_factor)

            if new_width < 100 or new_height < 100:
                break  # Don't make it too small

            resized_image = image.resize(
                (new_width, new_height), Image.Resampling.LANCZOS
            )

            output_buffer = BytesIO()
            resized_image.save(output_buffer, format="JPEG", quality=50, optimize=True)

            file_size = output_buffer.tell()

            if file_size <= max_file_size_bytes:
                return output_buffer.getvalue()

            scale_factor -= 0.1

        # Last resort: very aggressive compression
        logger.warning(
            f"Figure {figure_id} still too large after all attempts, "
            f"using last resort compression"
        )
        output_buffer = BytesIO()
        final_image = image.resize((800, 600), Image.Resampling.LANCZOS)
        final_image.save(output_buffer, format="JPEG", quality=30, optimize=True)

        return output_buffer.getvalue()

    def _build_prompt(
        self, paper_title: str, paper_abstract: str, num_figures: int
    ) -> str:
        """
        Build the prompt for Bedrock with scoring criteria.
        """
        criteria_section = "\n\n## Scoring Criteria (Total Weight: 100%)\n\n"
        for criterion_name, criterion_data in CRITERIA_DESCRIPTIONS.items():
            title = criterion_name.replace("_", " ").title()
            weight = criterion_data["weight"]
            desc = criterion_data["description"]
            metrics = criterion_data["key_metrics"]
            criteria_section += (
                f"- **{title} ({weight}%)**: {desc}\n" f"  - Key Metrics: {metrics}\n\n"
            )

        prompt = (
            f"""You are an expert at analyzing scientific paper figures """
            f"""and selecting the most appropriate primary image for """
            f"""display in a research feed.

## Paper Information

**Title:** {paper_title}

**Abstract:** {paper_abstract}

## Task

You will be shown {num_figures} images extracted from this paper.
These may include scientific figures, charts, diagrams, illustrations, logos,
avatars, or other visual content from the paper.

**IMPORTANT: You must evaluate ALL images provided, regardless of their type.**
You must always return a JSON response with scores for all images. Never refuse
to evaluate an image or return an error message.

If an image is not related to science or the article content (e.g., a logo,
avatar, or unrelated illustration), you should still evaluate it, but assign
low scores (0-30) on criteria like "Scientific Impact" and "Narrative Context"
since it doesn't relate to the paper's content. Other criteria like "Visual
Quality" and "Social Media Potential" should still be evaluated based on the
image's visual appeal.

## Selection Priorities

When selecting the best primary image, prioritize figures that are:

1. **Readable and Clear**: Text should be large enough to read, labels should be
   legible, and the figure should have good contrast. Small text or poor contrast
   significantly reduces a figure's value as a cover image.

2. **Overview Figures**: Figures that provide an overview, summary, or introduction
   to the paper are highly valuable. These help readers understand the paper's
   main contribution at a glance.

3. **Eye-Catching and Visually Appealing**: The figure should stand out and be
   visually interesting. Good use of color, clear visual hierarchy, and engaging
   composition make figures more suitable for feed display.

4. **Methods Figures**: Figures showing methods (e.g., imaging, staining,
   experimental setups, animal models) can be excellent cover images if they are
   visually appealing and clearly presented. These help readers understand the
   research approach.

5. **Representative**: The figure should represent the paper's main findings or
   approach, but readability and visual appeal are equally important.

The goal is to choose the most visually appealing, readable, and representative
image for display in a research feed. Images that are not science-related will
naturally score lower overall and won't be selected unless they are exceptionally
visually appealing and relevant.

Your task is to evaluate each image based on the scoring criteria below and select
the best primary image. Always return valid JSON with scores for all images.

{criteria_section}
## Instructions

1. Evaluate each image on all 8 criteria above, assigning scores from 0-100
   for each criterion based on how well the image meets that criterion.

   **CRITICAL: You must always return JSON with scores for ALL images.**
   Never refuse to evaluate an image or return an error message. If an image
   is not science-related or not relevant to the article:
   - Assign low scores (0-30) to "Scientific Impact" and "Narrative Context"
   - Still evaluate other criteria (Visual Quality, Social Media Potential,
     etc.) based on the image's actual visual appeal
   - The low scores will naturally prevent non-relevant images from being
     selected unless they are exceptionally visually appealing

   **Scoring Guidelines:**
   - 0-30: Poor - figure does not meet the criterion well
   - 31-50: Below average - figure partially meets the criterion
   - 51-70: Good - figure meets the criterion adequately
   - 71-85: Very good - figure meets the criterion well
   - 86-100: Excellent - figure exceeds the criterion

   **Be conservative in your scoring.** Most figures should score in the
   40-70 range. Only exceptional figures should score above 80. Reserve
   scores above 90 for truly outstanding figures that are ideal for feed
   display.

   **Special Considerations:**
   - **Readability**: If text is too small to read or contrast is poor,
     significantly reduce scores for Visual Quality and Interpretability (20-40).
   - **Overview Figures**: If a figure provides a good overview or summary,
     give higher scores for Narrative Context (70-90).
   - **Eye-Catching**: If a figure is particularly visually striking or
     eye-catching, give higher scores for Social Media Potential (75-95).
   - **Methods Figures**: Methods figures (imaging, staining, experimental
     setups) can score well on Scientific Impact (60-80) if they clearly
     represent the research approach.

2. Calculate the weighted total score by multiplying each criterion score by
   its weight percentage and summing them. The total_score should be a value
   from 0-100.

3. Select the figure that has the highest overall weighted score.

4. Return your response as JSON with the following format:
   {{
     "selected_figure_index": <0-based index of selected figure>,
     "scores": {{
       "figure_0": <total weighted score (0-100)>,
       "figure_1": <total weighted score (0-100)>,
       ...
     }}
   }}

   Note: You must evaluate all 8 criteria internally, but only return the
   total weighted score for each figure in the response.

Each image will be labeled as "Figure 0", "Figure 1", etc. in the order they
appear.

**Remember: Always return JSON with scores for ALL images. Never refuse to
evaluate or return an error. Non-relevant images should receive low scores
(0-30) on Scientific Impact and Narrative Context, but still be evaluated
on other criteria."""
        )

        return prompt

    def _get_response_schema(self, num_figures: int) -> dict:
        """
        Generate simplified JSON schema for the expected response structure.

        Only returns figure index => total score mapping, minimizing output tokens.
        """
        # Build schema for scores: figure_X => total_score (number)
        scores_properties = {}
        scores_required = []
        for i in range(num_figures):
            figure_key = f"figure_{i}"
            scores_properties[figure_key] = {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "description": f"Total weighted score for figure {i}",
            }
            scores_required.append(figure_key)

        return {
            "type": "object",
            "properties": {
                "selected_figure_index": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": num_figures - 1,
                    "description": "0-based index of the selected figure",
                },
                "scores": {
                    "type": "object",
                    "properties": scores_properties,
                    "required": scores_required,
                    "additionalProperties": False,
                },
            },
            "required": ["selected_figure_index", "scores"],
        }

    def _select_best_from_batch(
        self,
        batch_figures: List,
        paper_title: str,
        paper_abstract: str,
        batch_number: Optional[int] = None,
    ) -> Tuple[Optional[int], Optional[float]]:
        """
        Select the best figure from a batch of figures using AWS Bedrock.

        This is the core Bedrock API call logic that processes a single batch
        of figures (max MAX_IMAGES_PER_BEDROCK_REQUEST).
        """
        if not batch_figures:
            logger.warning("No figures provided for batch selection")
            return None, None

        if len(batch_figures) > MAX_IMAGES_PER_BEDROCK_REQUEST:
            logger.error(
                f"Batch contains {len(batch_figures)} figures, "
                f"exceeds limit of {MAX_IMAGES_PER_BEDROCK_REQUEST}"
            )
            return None, None

        batch_label = f"batch {batch_number}" if batch_number is not None else "batch"
        logger.info(
            f"Processing {batch_label} with {len(batch_figures)} figures "
            f"(figure IDs: {[f.id for f in batch_figures]})"
        )

        try:
            system_prompt = (
                "You are an expert scientific figure evaluator specializing in "
                "selecting the most appropriate primary images for research papers. "
                "You understand scientific visualization, data presentation, and "
                "what makes a figure suitable for public display in research feeds."
            )

            user_content = []
            prompt_text = self._build_prompt(
                paper_title, paper_abstract, len(batch_figures)
            )
            user_content.append({"text": prompt_text})

            # Add each figure as image content block
            figures_added = 0
            for idx, figure in enumerate(batch_figures):
                encoded_result = self._encode_image_to_base64(figure)
                if encoded_result is None:
                    logger.warning(f"Skipping figure {figure.id} - encoding failed")
                    continue

                base64_image, media_type = encoded_result

                image_format = "jpeg"
                if media_type == "image/png":
                    image_format = "png"
                elif media_type == "image/gif":
                    image_format = "gif"
                elif media_type == "image/webp":
                    image_format = "webp"

                user_content.append(
                    {
                        "image": {
                            "format": image_format,
                            "source": {
                                "bytes": base64.b64decode(base64_image),
                            },
                        },
                    }
                )

                user_content.append({"text": f"Figure {idx}"})
                figures_added += 1

            if figures_added == 0:
                logger.error(f"No figures could be encoded for {batch_label}")
                return None, None

            response_schema = self._get_response_schema(len(batch_figures))
            tools = [
                {
                    "toolSpec": {
                        "name": "evaluate_figures",
                        "description": (
                            "Evaluates scientific figures and returns structured "
                            "scores and selection. Use this tool to provide your "
                            "evaluation results."
                        ),
                        "inputSchema": {
                            "json": response_schema,
                        },
                    }
                }
            ]

            logger.info(
                f"Invoking Bedrock Converse API with Tool Use for {batch_label} "
                f"({len(batch_figures)} figures)"
            )

            # Use Converse API with Tool Use for structured responses
            response = self.bedrock_client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": user_content,
                    }
                ],
                toolConfig={
                    "tools": tools,
                },
                inferenceConfig={
                    "maxTokens": 4096,
                    "temperature": 0.0,
                },
            )

            if "output" not in response or not response["output"].get("message"):
                logger.error(
                    f"Invalid response from Bedrock for {batch_label}: "
                    f"missing output message"
                )
                return None, None

            message = response["output"]["message"]
            content = message.get("content", [])

            tool_result = None
            for content_block in content:
                if content_block.get("toolUse"):
                    tool_use = content_block["toolUse"]
                    if tool_use.get("name") == "evaluate_figures":
                        tool_result = tool_use.get("input")
                        break

            if tool_result is None:
                logger.error(
                    f"Bedrock response for {batch_label} missing tool use result. "
                    f"Response content: {content}",
                )
                return None, None

            result = tool_result
            selected_index = result.get("selected_figure_index")

            if selected_index is None:
                logger.error(
                    f"Bedrock response for {batch_label} missing "
                    f"selected_figure_index"
                )
                return None, None

            if selected_index < 0 or selected_index >= len(batch_figures):
                logger.error(
                    f"Invalid figure index {selected_index} for {batch_label} "
                    f"(must be 0-{len(batch_figures)-1})"
                )
                return None, None

            selected_figure = batch_figures[selected_index]

            scores = result.get("scores", {})
            figure_key = f"figure_{selected_index}"
            best_score = scores.get(figure_key)

            if best_score is None:
                logger.warning(
                    f"Bedrock response for {batch_label} missing score "
                    f"for selected figure {selected_index}"
                )

            logger.info(
                f"Bedrock selected figure index {selected_index} from "
                f"{batch_label} (figure ID: {selected_figure.id}, "
                f"score: {best_score})"
            )

            return selected_figure.id, best_score

        except Exception as e:
            sentry.log_error(e, message=f"Bedrock API call failed for {batch_label}")
            logger.exception(f"Exception details for {batch_label}")
            return None, None

    def select_primary_image(
        self, paper_title: str, paper_abstract: str, figures: List
    ) -> Tuple[Optional[int], Optional[float]]:
        """
        Select primary image from figures using AWS Bedrock with batching support.

        If there are more than MAX_IMAGES_PER_BEDROCK_REQUEST figures, this method
        will process them in batches, select winners from each batch, and then
        select the overall best from the batch winners.

        Args:
            paper_title: Title of the paper
            paper_abstract: Abstract of the paper
            figures: List of Figure model instances

        Returns:
            Tuple of (selected_figure_id, best_score) or (None, None) if selection fails
            best_score is the total_score from Bedrock response (0-100)
        """
        if not figures:
            logger.warning("No figures provided for primary image selection")
            return None, None

        num_figures = len(figures)
        logger.info(f"Selecting primary image from {num_figures} figures")

        # If we have ≤ 20 figures, process directly
        if num_figures <= MAX_IMAGES_PER_BEDROCK_REQUEST:
            logger.info(
                f"Processing {num_figures} figures directly "
                f"(within limit of {MAX_IMAGES_PER_BEDROCK_REQUEST})"
            )
            return self._select_best_from_batch(figures, paper_title, paper_abstract)

        logger.info(
            f"Processing {num_figures} figures in batches "
            f"(limit: {MAX_IMAGES_PER_BEDROCK_REQUEST} per batch)"
        )

        batches = []
        for i in range(0, num_figures, MAX_IMAGES_PER_BEDROCK_REQUEST):
            batch = figures[i : i + MAX_IMAGES_PER_BEDROCK_REQUEST]  # noqa: E203
            batches.append(batch)

        batch_sizes = [len(batch) for batch in batches]
        logger.info(f"Created {len(batches)} batches with sizes: {batch_sizes}")

        batch_winners = []
        failed_batches = 0

        for batch_idx, batch in enumerate(batches, start=1):
            selected_id, score = self._select_best_from_batch(
                batch, paper_title, paper_abstract, batch_number=batch_idx
            )

            if selected_id is None or score is None:
                logger.warning(f"Batch {batch_idx} failed to select a winner, skipping")
                failed_batches += 1
                continue

            # Find the figure object from the selected ID
            selected_figure = next((f for f in batch if f.id == selected_id), None)
            if selected_figure is None:
                logger.warning(
                    f"Could not find figure {selected_id} from batch {batch_idx}"
                )
                failed_batches += 1
                continue

            batch_winners.append((selected_figure, score))
            logger.info(
                f"Batch {batch_idx} winner: figure {selected_id} (score: {score})"
            )

        if not batch_winners:
            logger.error(f"All {len(batches)} batches failed to select winners")
            return None, None

        if failed_batches > 0:
            logger.warning(
                f"{failed_batches} out of {len(batches)} batches failed, "
                f"proceeding with {len(batch_winners)} winners"
            )

        if len(batch_winners) == 1:
            winner_figure, winner_score = batch_winners[0]
            logger.info(
                f"Single batch winner selected as primary: "
                f"figure {winner_figure.id} (score: {winner_score})"
            )
            return winner_figure.id, winner_score

        if len(batch_winners) <= MAX_IMAGES_PER_BEDROCK_REQUEST:
            logger.info(f"Selecting best from {len(batch_winners)} batch winners")
            winner_figures = [figure for figure, _ in batch_winners]
            selected_id, final_score = self._select_best_from_batch(
                winner_figures,
                paper_title,
                paper_abstract,
                batch_number="final",
            )

            if selected_id is None or final_score is None:
                logger.warning(
                    "Final selection failed, using highest scoring batch winner"
                )
                best_winner = max(batch_winners, key=lambda x: x[1] if x[1] else 0)
                winner_figure, winner_score = best_winner
                return winner_figure.id, winner_score

            logger.info(f"Final selection: figure {selected_id} (score: {final_score})")
            return selected_id, final_score

        logger.info(
            f"Recursively batching {len(batch_winners)} winners "
            f"(exceeds limit of {MAX_IMAGES_PER_BEDROCK_REQUEST})"
        )
        winner_figures = [figure for figure, _ in batch_winners]
        return self.select_primary_image(paper_title, paper_abstract, winner_figures)
