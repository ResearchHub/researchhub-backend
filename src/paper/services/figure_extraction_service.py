"""
Service for extracting figures from PDF documents using PyMuPDF.
"""

import base64
import logging
from io import BytesIO
from typing import List, Tuple

import fitz
from django.core.files.base import ContentFile
from PIL import Image

logger = logging.getLogger(__name__)

# Minimum dimensions for extracted figures (pixels)
MIN_FIGURE_WIDTH = 600
MIN_FIGURE_HEIGHT = 600

# Maximum aspect ratio (width:height) - filters out very wide images like headers/footers
MAX_ASPECT_RATIO = 3.0  # 3:1

# Minimum aspect ratio (width:height) - filters out very tall/narrow images
MIN_ASPECT_RATIO = 1.0 / 3.0  # 1:3


class FigureExtractionService:
    """Service for extracting figures from PDF documents."""

    def extract_figures_from_pdf(
        self, pdf_content: bytes, paper_id: int
    ) -> List[Tuple[ContentFile, dict]]:
        """
        Extract embedded images from PDF content.

        Args:
            pdf_content: PDF file content as bytes
            paper_id: ID of the paper (for naming extracted figures)

        Returns:
            List of tuples containing (ContentFile, metadata_dict) for each extracted figure
            Metadata dict contains: width, height, page_number, image_index
        """
        extracted_figures = []

        try:
            doc = fitz.open(stream=pdf_content, filetype="pdf")

            for page_num, page in enumerate(doc):
                try:
                    # Get embedded images from this page
                    image_list = page.get_images(full=True)

                    for img_index, img in enumerate(image_list):
                        try:
                            xref = img[0]  # Image reference number

                            # Extract image data
                            base_image = doc.extract_image(xref)
                            image_bytes = base_image["image"]
                            image_ext = base_image["ext"]

                            # Convert to PIL Image to check dimensions
                            img_buffer = BytesIO(image_bytes)
                            pil_image = Image.open(img_buffer)
                            width, height = pil_image.size

                            # Calculate aspect ratio
                            aspect_ratio = width / height if height > 0 else 0

                            # Filter by minimum size
                            if width < MIN_FIGURE_WIDTH or height < MIN_FIGURE_HEIGHT:
                                logger.debug(
                                    f"Skipping image {img_index} on page {page_num}: "
                                    f"too small ({width}x{height})"
                                )
                                continue

                            # Filter by aspect ratio
                            if (
                                aspect_ratio > MAX_ASPECT_RATIO
                                or aspect_ratio < MIN_ASPECT_RATIO
                            ):
                                logger.debug(
                                    f"Skipping image {img_index} on page {page_num}: "
                                    f"extreme aspect ratio ({aspect_ratio:.2f})"
                                )
                                continue

                            # Create filename
                            filename = (
                                f"{paper_id}-page{page_num}-img{img_index}.{image_ext}"
                            )

                            # Create ContentFile
                            content_file = ContentFile(image_bytes, name=filename)

                            # Store metadata
                            metadata = {
                                "width": width,
                                "height": height,
                                "page_number": page_num,
                                "image_index": img_index,
                                "aspect_ratio": aspect_ratio,
                            }

                            extracted_figures.append((content_file, metadata))

                            logger.info(
                                f"Extracted figure from page {page_num}, "
                                f"image {img_index}: {width}x{height} (aspect: {aspect_ratio:.2f})"
                            )

                        except Exception as e:
                            logger.warning(
                                f"Error extracting image {img_index} from page {page_num}: {e}"
                            )
                            continue

                except Exception as e:
                    logger.warning(f"Error processing page {page_num}: {e}")
                    continue

            doc.close()

        except Exception as e:
            logger.error(f"Error extracting figures from PDF: {e}")
            raise

        logger.info(f"Extracted {len(extracted_figures)} figures from PDF")
        return extracted_figures
