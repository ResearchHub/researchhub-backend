import json
import logging
from typing import List, Optional

from utils import sentry
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Amazon Titan Text Embeddings V2 model
# Outputs 1024-dimensional vectors by default
BEDROCK_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Maximum input text length for Titan embeddings (in characters)
# The model supports up to 8192 tokens, but we'll limit by characters for safety
MAX_INPUT_TEXT_LENGTH = 25000


class BedrockEmbeddingService:
    """Service for generating text embeddings using AWS Bedrock."""

    def __init__(self):
        self.bedrock_client = create_client("bedrock-runtime")
        self.model_id = BEDROCK_EMBEDDING_MODEL_ID

    def generate_embedding(
        self,
        text: str,
        normalize: bool = True,
        dimensions: int = 1024,
    ) -> Optional[List[float]]:
        """
        Generate an embedding vector for the given text using Amazon Titan.

        Args:
            text: The text to generate an embedding for.
            normalize: Whether to normalize the embedding vector (default True).
            dimensions: The output dimension (256, 512, or 1024). Default 1024.

        Returns:
            A list of floats representing the embedding vector, or None if generation fails.
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding generation")
            return None

        # Truncate text if it exceeds the maximum length
        if len(text) > MAX_INPUT_TEXT_LENGTH:
            logger.warning(
                f"Text exceeds maximum length ({len(text)} > {MAX_INPUT_TEXT_LENGTH}), "
                f"truncating"
            )
            text = text[:MAX_INPUT_TEXT_LENGTH]

        try:
            # Prepare the request body for Amazon Titan Text Embeddings V2
            request_body = {
                "inputText": text,
                "dimensions": dimensions,
                "normalize": normalize,
            }

            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            response_body = json.loads(response["body"].read())
            embedding = response_body.get("embedding")

            if embedding is None:
                logger.error("No embedding found in Bedrock response")
                return None

            logger.debug(
                f"Generated embedding with {len(embedding)} dimensions "
                f"for text of length {len(text)}"
            )

            return embedding

        except Exception as e:
            sentry.log_error(e, message="Failed to generate embedding via Bedrock")
            logger.exception("Exception during embedding generation")
            return None

    def generate_paper_embedding(
        self,
        title: str,
        abstract: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        Generate an embedding for a paper using its title and abstract.

        The title and abstract are combined into a single text representation
        that captures the semantic meaning of the paper.

        Args:
            title: The paper's title (required).
            abstract: The paper's abstract (optional, but recommended).

        Returns:
            A list of floats representing the embedding vector, or None if generation fails.
        """
        if not title:
            logger.warning("No title provided for paper embedding generation")
            return None

        # Combine title and abstract into a structured text representation
        if abstract and abstract.strip():
            # Format: "Title: {title}\n\nAbstract: {abstract}"
            combined_text = f"Title: {title}\n\nAbstract: {abstract}"
        else:
            # If no abstract, just use the title
            combined_text = f"Title: {title}"

        return self.generate_embedding(combined_text)
