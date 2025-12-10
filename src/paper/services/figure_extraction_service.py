import logging
from io import BytesIO
from typing import List, Tuple

import fitz
from django.core.files.base import ContentFile
from PIL import Image

logger = logging.getLogger(__name__)

# Minimum dimensions for extracted figures (pixels)
MIN_FIGURE_WIDTH = 400
MIN_FIGURE_HEIGHT = 400

# Maximum dimensions for extracted figures (pixels)
MAX_FIGURE_WIDTH = 2000
MAX_FIGURE_HEIGHT = 2000

# Maximum aspect ratio (width:height)
MAX_ASPECT_RATIO = 3.0  # 3:1

# Minimum aspect ratio (width:height) - filters out very tall/narrow images
MIN_ASPECT_RATIO = 1.0 / 3.0  # 1:3

JPEG_QUALITY = 85


class FigureExtractionService:
    """Service for extracting figures from PDF documents."""

    def extract_figures_from_pdf(
        self, pdf_content: bytes, paper_id: int
    ) -> List[Tuple[ContentFile, dict]]:
        """
        Extract embedded images from PDF content.
        """
        extracted_figures = []

        try:
            doc = fitz.open(stream=pdf_content, filetype="pdf")

            for page_num, page in enumerate(doc):
                try:
                    image_list = page.get_images(full=True)

                    for img_index, img in enumerate(image_list):
                        try:
                            xref = img[0]
                            base_image = doc.extract_image(xref)
                            image_bytes = base_image["image"]
                            image_ext = base_image["ext"]

                            img_buffer = BytesIO(image_bytes)
                            pil_image = Image.open(img_buffer)
                            width, height = pil_image.size
                            aspect_ratio = width / height if height > 0 else 0

                            if width < MIN_FIGURE_WIDTH or height < MIN_FIGURE_HEIGHT:
                                logger.debug(
                                    f"Skipping image {img_index} on page {page_num}: "
                                    f"too small ({width}x{height})"
                                )
                                continue

                            if (
                                aspect_ratio > MAX_ASPECT_RATIO
                                or aspect_ratio < MIN_ASPECT_RATIO
                            ):
                                logger.debug(
                                    f"Skipping image {img_index} on page {page_num}: "
                                    f"extreme aspect ratio ({aspect_ratio:.2f})"
                                )
                                continue

                            original_width, original_height = width, height
                            if width > MAX_FIGURE_WIDTH or height > MAX_FIGURE_HEIGHT:
                                pil_image = self._resize_image(
                                    pil_image, MAX_FIGURE_WIDTH, MAX_FIGURE_HEIGHT
                                )
                                width, height = pil_image.size
                                logger.info(
                                    f"Resized image {img_index} on page "
                                    f"{page_num} from {original_width}x"
                                    f"{original_height} to {width}x{height}"
                                )

                            output_buffer = BytesIO()
                            # Convert RGBA to RGB (JPEG doesn't support alpha channel)
                            if pil_image.mode in ("RGBA", "LA", "P"):
                                rgb_image = Image.new(
                                    "RGB", pil_image.size, (255, 255, 255)
                                )
                                if pil_image.mode == "P":
                                    pil_image = pil_image.convert("RGBA")
                                mask = (
                                    pil_image.split()[-1]
                                    if pil_image.mode == "RGBA"
                                    else None
                                )
                                rgb_image.paste(pil_image, mask=mask)
                                pil_image = rgb_image

                            pil_image.save(
                                output_buffer,
                                format="JPEG",
                                quality=JPEG_QUALITY,
                                optimize=True,
                            )
                            image_bytes = output_buffer.getvalue()
                            image_ext = "jpg"

                            filename = (
                                f"{paper_id}-page{page_num}-img{img_index}.{image_ext}"
                            )
                            content_file = ContentFile(image_bytes, name=filename)

                            was_resized = (
                                width != original_width or height != original_height
                            )
                            metadata = {
                                "width": width,
                                "height": height,
                                "original_width": original_width,
                                "original_height": original_height,
                                "page_number": page_num,
                                "image_index": img_index,
                                "aspect_ratio": aspect_ratio,
                                "resized": was_resized,
                            }

                            extracted_figures.append((content_file, metadata))

                            logger.info(
                                f"Extracted figure from page {page_num}, "
                                f"image {img_index}: {width}x{height} "
                                f"(aspect: {aspect_ratio:.2f})"
                            )

                        except Exception as e:
                            logger.warning(
                                f"Error extracting image {img_index} "
                                f"from page {page_num}: {e}"
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

    def _resize_image(
        self, image: Image.Image, max_width: int, max_height: int
    ) -> Image.Image:
        """
        Resize image to fit within maximum dimensions.
        """
        width, height = image.size
        scale = min(max_width / width, max_height / height)

        if scale < 1.0:
            new_width = int(width * scale)
            new_height = int(height * scale)
            resized_image = image.resize(
                (new_width, new_height), Image.Resampling.LANCZOS
            )
            return resized_image

        return image
