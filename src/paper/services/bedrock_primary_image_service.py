"""
Service for using AWS Bedrock to select the primary image from extracted figures.
"""

import base64
import json
import logging
from typing import List, Optional

from django.conf import settings

from paper.constants.figure_selection_criteria import CRITERIA_DESCRIPTIONS
from utils import aws as aws_utils

logger = logging.getLogger(__name__)


class BedrockPrimaryImageService:
    """Service for selecting primary image using AWS Bedrock."""

    def __init__(self):
        self.bedrock_client = aws_utils.create_bedrock_client()
        self.model_id = getattr(settings, "AWS_BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

    def _encode_image_to_base64(self, figure) -> Optional[tuple]:
        """
        Encode figure image to base64 string.

        Args:
            figure: Figure model instance

        Returns:
            Tuple of (base64_image_string, media_type) or None if encoding fails
        """
        try:
            if not figure.file:
                return None

            # Read file content
            figure.file.open("rb")
            image_bytes = figure.file.read()
            figure.file.close()

            # Encode to base64
            base64_image = base64.b64encode(image_bytes).decode("utf-8")

            # Determine media type from file extension
            file_name = figure.file.name.lower()
            if file_name.endswith(".png"):
                media_type = "image/png"
            elif file_name.endswith(".jpg") or file_name.endswith(".jpeg"):
                media_type = "image/jpeg"
            else:
                media_type = "image/png"  # Default

            return base64_image, media_type

        except Exception as e:
            logger.error(f"Error encoding figure {figure.id} to base64: {e}")
            return None

    def _build_prompt(self, paper_title: str, paper_abstract: str, num_figures: int) -> str:
        """
        Build the prompt for Bedrock with scoring criteria.
        
        Args:
            paper_title: Title of the paper
            paper_abstract: Abstract of the paper
            num_figures: Number of figures to evaluate
            
        Returns:
            Formatted prompt string
        """
        # Build criteria section
        criteria_section = "\n\n## Scoring Criteria (Total Weight: 100%)\n\n"
        for criterion_name, criterion_data in CRITERIA_DESCRIPTIONS.items():
            criteria_section += (
                f"- **{criterion_name.replace('_', ' ').title()} ({criterion_data['weight']}%)**: "
                f"{criterion_data['description']}\n"
                f"  - Key Metrics: {criterion_data['key_metrics']}\n\n"
            )
        
        prompt = f"""You are an expert at analyzing scientific paper figures and selecting the most appropriate primary image for display in a research feed.

## Paper Information

**Title:** {paper_title}

**Abstract:** {paper_abstract}

## Task

You will be shown {num_figures} figures extracted from this paper. Your task is to evaluate each figure based on the scoring criteria below and select the best primary image.

{criteria_section}
## Instructions

1. Evaluate each figure on all 8 criteria above, assigning scores based on how well each figure meets the criteria.
2. Consider the weights when calculating overall scores.
3. Select the figure that has the highest overall weighted score.
4. Return your response as JSON with the following format:
   {{
     "selected_figure_index": <0-based index of selected figure>,
     "scores": {{
       "figure_0": {{
         "aspect_ratio_match": <score>,
         "scientific_impact": <score>,
         "visual_quality": <score>,
         "data_density": <score>,
         "narrative_context": <score>,
         "interpretability": <score>,
         "uniqueness": <score>,
         "social_media_potential": <score>,
         "total_score": <weighted total>
       }},
       ...
     }},
     "reasoning": "<brief explanation of why this figure was selected>"
   }}

Each figure will be labeled as "Figure 0", "Figure 1", etc. in the order they appear."""
        
        return prompt

    def select_primary_image(
        self, paper_title: str, paper_abstract: str, figures: List
    ) -> Optional[int]:
        """
        Select primary image from figures using AWS Bedrock.
        
        Args:
            paper_title: Title of the paper
            paper_abstract: Abstract of the paper
            figures: List of Figure model instances
            
        Returns:
            ID of the selected figure, or None if selection fails
        """
        if not figures:
            logger.warning("No figures provided for primary image selection")
            return None
        
        try:
            # Build system prompt
            system_prompt = (
                "You are an expert scientific figure evaluator specializing in "
                "selecting the most appropriate primary images for research papers. "
                "You understand scientific visualization, data presentation, and "
                "what makes a figure suitable for public display in research feeds."
            )
            
            # Build user message content
            user_content = []
            
            # Add text prompt
            prompt_text = self._build_prompt(paper_title, paper_abstract, len(figures))
            user_content.append({"type": "text", "text": prompt_text})
            
            # Add each figure as image content block
            for idx, figure in enumerate(figures):
                encoded_result = self._encode_image_to_base64(figure)
                if encoded_result is None:
                    logger.warning(f"Skipping figure {figure.id} - encoding failed")
                    continue
                
                base64_image, media_type = encoded_result
                
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_image,
                    },
                })
                
                user_content.append({
                    "type": "text",
                    "text": f"Figure {idx}",
                })
            
            if not any(item.get("type") == "image" for item in user_content):
                logger.error("No figures could be encoded for Bedrock")
                return None
            
            # Prepare request body
            request_body = {
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
            
            # Invoke Bedrock model
            logger.info(
                f"Invoking Bedrock model {self.model_id} to select primary image "
                f"from {len(figures)} figures"
            )
            
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
            )
            
            # Parse response
            response_body = json.loads(response["body"].read())
            
            if "content" not in response_body:
                logger.error("Invalid response from Bedrock: missing content")
                return None
            
            # Extract text from response
            text_content = ""
            for content_block in response_body["content"]:
                if content_block.get("type") == "text":
                    text_content += content_block.get("text", "")
            
            # Parse JSON from response
            try:
                # Try to extract JSON from the response text
                # The model might return JSON wrapped in markdown code blocks
                if "```json" in text_content:
                    json_start = text_content.find("```json") + 7
                    json_end = text_content.find("```", json_start)
                    json_text = text_content[json_start:json_end].strip()
                elif "```" in text_content:
                    json_start = text_content.find("```") + 3
                    json_end = text_content.find("```", json_start)
                    json_text = text_content[json_start:json_end].strip()
                else:
                    # Try to find JSON object in the text
                    json_start = text_content.find("{")
                    json_end = text_content.rfind("}") + 1
                    json_text = text_content[json_start:json_end]
                
                result = json.loads(json_text)
                selected_index = result.get("selected_figure_index")
                
                if selected_index is None:
                    logger.error("Bedrock response missing selected_figure_index")
                    return None
                
                if selected_index < 0 or selected_index >= len(figures):
                    logger.error(
                        f"Invalid figure index {selected_index} "
                        f"(must be 0-{len(figures)-1})"
                    )
                    return None
                
                selected_figure = figures[selected_index]
                logger.info(
                    f"Bedrock selected figure index {selected_index} "
                    f"(figure ID: {selected_figure.id})"
                )
                
                # Log reasoning if provided
                if "reasoning" in result:
                    logger.info(f"Selection reasoning: {result['reasoning']}")
                
                return selected_figure.id
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from Bedrock response: {e}")
                logger.error(f"Response text: {text_content[:500]}")
                return None
                
        except Exception as e:
            logger.error(f"Error calling Bedrock API: {e}")
            raise

