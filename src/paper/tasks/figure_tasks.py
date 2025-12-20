from io import BytesIO

import fitz
import requests
from celery.utils.log import get_task_logger
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image

from paper.models import Figure, Paper
from paper.services.bedrock_primary_image_service import (
    MIN_PRIMARY_SCORE_THRESHOLD,
    BedrockPrimaryImageService,
)
from paper.services.figure_extraction_service import FigureExtractionService
from paper.tasks.tasks import create_download_url
from paper.utils import download_pdf_from_url, get_cache_key
from researchhub.celery import QUEUE_PAPER_MISC, app
from researchhub.settings import PRODUCTION
from utils import sentry

logger = get_task_logger(__name__)

MIN_HOT_SCORE_FOR_FIGURE_EXTRACTION = 75


def generate_thumbnail_for_figure(figure) -> bool:
    """
    Generate and save a WebP thumbnail for a figure.

    This should be called when a figure is selected as primary image.
    Thumbnails are only needed for primary images displayed in feeds.

    Args:
        figure: Figure model instance

    Returns:
        True if thumbnail was generated successfully, False otherwise
    """
    try:
        if not figure.file:
            logger.warning(f"Figure {figure.id} has no file, cannot generate thumbnail")
            return False

        # Read the figure image
        figure.file.open("rb")
        image_bytes = figure.file.read()
        figure.file.close()

        # Open with PIL
        img_buffer = BytesIO(image_bytes)
        pil_image = Image.open(img_buffer)

        # Get base filename without extension
        filename = figure.file.name.split("/")[-1]
        filename_base = filename.rsplit(".", 1)[0]

        # Generate thumbnail using extraction service
        extraction_service = FigureExtractionService()
        thumbnail_file = extraction_service.create_thumbnail(pil_image, filename_base)

        # Save thumbnail to figure
        figure.thumbnail = thumbnail_file
        figure.save(update_fields=["thumbnail"])

        logger.info(f"Generated thumbnail for figure {figure.id}")
        return True

    except Exception as e:
        logger.error(f"Error generating thumbnail for figure {figure.id}: {e}")
        sentry.log_error(e)
        return False


@app.task(queue=QUEUE_PAPER_MISC)
def celery_extract_pdf_preview(paper_id, retry=0):
    if paper_id is None or retry > 2:
        print("No paper id for pdf preview")
        return False

    print(f"Extracting pdf figures for paper: {paper_id}")

    Paper = apps.get_model("paper.Paper")
    Figure = apps.get_model("paper.Figure")
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        print(f"No file exists for paper: {paper_id}")
        celery_extract_pdf_preview.apply_async(
            (paper.id, retry + 1),
            priority=6,
            countdown=10,
        )
        return False

    file_url = file.url

    try:
        res = requests.get(file_url)
        doc = fitz.open(stream=res.content, filetype="pdf")
        extracted_figures = Figure.objects.filter(paper=paper)
        for page in doc:
            pix = page.get_pixmap(alpha=False)
            output_filename = f"{paper_id}-{page.number}.png"

            if not extracted_figures.filter(
                file__contains=output_filename, figure_type=Figure.PREVIEW
            ):
                img_buffer = BytesIO()
                img_buffer.write(pix.pil_tobytes(format="PNG"))
                image = Image.open(img_buffer)
                image.save(img_buffer, "png", quality=0)
                file = ContentFile(img_buffer.getvalue(), name=output_filename)
                Figure.objects.create(
                    file=file,
                    paper=paper,
                    figure_type=Figure.PREVIEW,
                    thumbnail=None,
                )
    except Exception as e:
        sentry.log_error(e)
    finally:
        cache_key = get_cache_key("figure", paper_id)
        cache.delete(cache_key)
    return True


@app.task(queue=QUEUE_PAPER_MISC, bind=True)
def extract_pdf_figures(
    self,
    paper_id,
    retry=0,
    skip_feed_refresh_extraction_check=False,
    sync_primary_selection=False,
):
    if retry > 2:
        logger.warning(f"Max retries reached for figure extraction - paper {paper_id}")
        return False

    Paper = apps.get_model("paper.Paper")
    Figure = apps.get_model("paper.Figure")

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.warning(f"Paper {paper_id} not found")
        return False

    file = paper.file
    pdf_content = None

    # Try to get PDF content from file first
    if file:
        try:
            file_url = file.url
            res = requests.get(file_url, timeout=60)
            res.raise_for_status()
            pdf_content = res.content
            logger.info(f"Using PDF file for paper {paper_id}")
        except Exception as e:
            logger.warning(
                f"Failed to get PDF from file for paper {paper_id}: {e}. "
                f"Trying pdf_url..."
            )
            pdf_content = None

    # If no file or file failed, try pdf_url
    if not pdf_content and paper.pdf_url:
        try:
            logger.info(
                f"No PDF file for paper {paper_id}, downloading from pdf_url: "
                f"{paper.pdf_url}"
            )
            url = create_download_url(paper.pdf_url, paper.external_source)
            pdf_file = download_pdf_from_url(url)
            pdf_content = pdf_file.read()

        except Exception as e:
            logger.warning(
                f"Failed to download PDF from pdf_url for paper {paper_id}: {e}"
            )
            pdf_content = None

    if not pdf_content:
        logger.info(
            f"No PDF content available for paper {paper_id} "
            f"(file={bool(file)}, pdf_url={bool(paper.pdf_url)}), retrying..."
        )
        extract_pdf_figures.apply_async(
            (paper.id, retry + 1),
            {
                "skip_feed_refresh_extraction_check": (
                    skip_feed_refresh_extraction_check
                ),
                "sync_primary_selection": sync_primary_selection,
            },
            priority=6,
            countdown=10 * (retry + 1),
        )
        return False

    try:

        # Extract figures using service
        extraction_service = FigureExtractionService()
        extracted_figures = extraction_service.extract_figures_from_pdf(
            pdf_content, paper_id
        )

        # Save extracted figures to database
        figures_created = 0
        with transaction.atomic():
            for content_file in extracted_figures:
                # Check if figure already exists (avoid duplicates)
                filename = content_file.name.split("/")[-1]
                existing_figure = Figure.objects.filter(
                    paper=paper,
                    figure_type=Figure.FIGURE,
                    file__contains=filename,
                ).first()

                if not existing_figure:
                    Figure.objects.create(
                        file=content_file,
                        paper=paper,
                        figure_type=Figure.FIGURE,
                        thumbnail=None,
                    )
                    figures_created += 1

        logger.info(
            f"Extracted {figures_created} new figures for paper {paper_id} "
            f"(total extracted: {len(extracted_figures)})"
        )

        # Clear cache
        cache_key = get_cache_key("figure", paper_id)
        cache.delete(cache_key)

        # Select primary image after extraction
        if sync_primary_selection:
            try:
                select_primary_image(
                    paper.id,
                    skip_feed_refresh_extraction_check=(
                        skip_feed_refresh_extraction_check
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"Failed to select primary image for paper {paper_id}: {e}. "
                    f"Figures were extracted successfully."
                )
                sentry.log_error(e)
        else:
            select_primary_image.apply_async(
                (paper.id,),
                {
                    "skip_feed_refresh_extraction_check": (
                        skip_feed_refresh_extraction_check
                    )
                },
                priority=5,
            )

        logger.info(f"Successfully extracted figures for paper {paper_id}")

        return True

    except Exception as e:
        logger.error(f"Error extracting figures for paper {paper_id}: {e}")
        sentry.log_error(e)

        # Retry on failure
        if retry < 2:
            extract_pdf_figures.apply_async(
                (paper.id, retry + 1),
                {
                    "skip_feed_refresh_extraction_check": (
                        skip_feed_refresh_extraction_check
                    ),
                    "sync_primary_selection": sync_primary_selection,
                },
                priority=6,
                countdown=30 * (retry + 1),
            )

        return False


def trigger_figure_extraction_for_paper(paper_id, hot_score_v2):
    """
    Check if figure extraction should be triggered for a paper when hot_score_v2
    is recalculated in feed tasks. Only triggers in PRODUCTION environment.

    Returns:
        bool: True if extraction was triggered, False otherwise
    """
    try:
        if not PRODUCTION:
            logger.debug(
                f"Skipping figure extraction for paper {paper_id} "
                f"(not in production, hot_score_v2={hot_score_v2})"
            )
            return False

        if hot_score_v2 < MIN_HOT_SCORE_FOR_FIGURE_EXTRACTION:
            return False

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            logger.warning(f"Paper {paper_id} not found for figure extraction check")
            return False

        if Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE).exists():
            logger.debug(
                f"Paper {paper_id} already has figures extracted, skipping extraction"
            )
            return False

        logger.info(
            f"Triggering figure extraction for paper {paper_id} "
            f"(hot_score_v2={hot_score_v2} >= {MIN_HOT_SCORE_FOR_FIGURE_EXTRACTION})"
        )
        extract_pdf_figures.apply_async(
            (paper.id,),
            {"skip_feed_refresh_extraction_check": True},
            priority=6,
        )
        return True

    except Exception as e:
        logger.error(
            f"Error checking/triggering figure extraction for paper {paper_id}: {e}",
            exc_info=True,
        )
        return False


def create_pdf_screenshot(paper, skip_feed_refresh_extraction_check=False) -> bool:
    """
    Create a preview (screenshot) of the first page of the PDF and mark it as primary.

    Args:
        paper: Paper model instance

    Returns:
        True if preview was created successfully, False otherwise
    """
    Figure = apps.get_model("paper.Figure")

    try:
        file = paper.file
        if not file:
            logger.warning(f"No PDF file for paper {paper.id}, cannot create preview")
            return False

        # Check if preview already exists (first page preview)
        existing_preview = Figure.objects.filter(
            paper=paper, figure_type=Figure.PREVIEW
        ).first()

        if existing_preview:
            # Mark existing preview as primary
            Figure.objects.filter(paper=paper).update(is_primary=False)
            existing_preview.is_primary = True
            existing_preview.save(update_fields=["is_primary"])

            # Refresh feed entries to update cached primary_image and thumbnail
            from feed.tasks import refresh_feed_entries_for_objects

            Paper = apps.get_model("paper.Paper")
            paper_content_type = ContentType.objects.get_for_model(Paper)
            refresh_feed_entries_for_objects.delay(
                paper.id,
                paper_content_type.id,
                skip_figure_extraction=skip_feed_refresh_extraction_check,
            )

            logger.info(f"Using existing preview for paper {paper.id}")
            return True

        # Get PDF content
        file_url = file.url
        res = requests.get(file_url, timeout=60)
        res.raise_for_status()
        pdf_content = res.content

        # Open PDF and get first page
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        if len(doc) == 0:
            logger.warning(f"PDF has no pages for paper {paper.id}")
            doc.close()
            return False

        # Get first page as image (2x zoom for better quality)
        first_page = doc[0]
        pix = first_page.get_pixmap(alpha=False, matrix=fitz.Matrix(2, 2))

        # Convert to PNG
        img_buffer = BytesIO()
        img_buffer.write(pix.pil_tobytes(format="PNG"))
        image = Image.open(img_buffer)
        image.save(img_buffer, "PNG")

        # Create filename
        output_filename = f"{paper.id}-preview-page0.png"
        content_file = ContentFile(img_buffer.getvalue(), name=output_filename)

        # Create thumbnail using FigureExtractionService
        extraction_service = FigureExtractionService()
        thumbnail_file = extraction_service.create_thumbnail(
            image, f"{paper.id}-preview-page0"
        )

        # Create figure as PREVIEW type with thumbnail
        preview_figure = Figure.objects.create(
            file=content_file,
            thumbnail=thumbnail_file,
            paper=paper,
            figure_type=Figure.PREVIEW,
            is_primary=True,
        )

        # Clear any other primary flags
        Figure.objects.filter(paper=paper).exclude(id=preview_figure.id).update(
            is_primary=False
        )

        doc.close()

        # Refresh feed entries to update cached primary_image and thumbnail
        from feed.tasks import refresh_feed_entries_for_objects

        Paper = apps.get_model("paper.Paper")
        paper_content_type = ContentType.objects.get_for_model(Paper)
        refresh_feed_entries_for_objects.delay(
            paper.id,
            paper_content_type.id,
            skip_figure_extraction=skip_feed_refresh_extraction_check,
        )

        logger.info(
            f"Created preview with thumbnail for paper {paper.id}: {output_filename}"
        )
        return True

    except Exception as e:
        logger.error(f"Error creating preview for paper {paper.id}: {e}")
        sentry.log_error(e)
        return False


@app.task(queue=QUEUE_PAPER_MISC, bind=True)
def select_primary_image(
    self, paper_id, retry=0, skip_feed_refresh_extraction_check=False
):
    """
    Use AWS Bedrock to select the primary image from extracted figures.
    This task will:
    - Recalculate and select best figure if figures exist
    - Keep existing primary if already set and no figures
    - Create preview as fallback if needed
    """
    if retry > 2:
        logger.warning(
            f"Max retries reached for primary image selection - paper {paper_id}"
        )
        return False

    Paper = apps.get_model("paper.Paper")
    Figure = apps.get_model("paper.Figure")

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.warning(f"Paper {paper_id} not found")
        return False

    figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE).order_by(
        "created_date"
    )

    if not figures.exists():
        # Check if there's already a primary figure (could be a preview)
        existing_primary = Figure.objects.filter(paper=paper, is_primary=True).first()

        if existing_primary:
            logger.info(
                f"No figures found for paper {paper_id}, "
                f"but primary figure already exists: {existing_primary.id} "
                f"(type: {existing_primary.figure_type})"
            )
            return True

        logger.info(f"No figures found for paper {paper_id}, creating preview")
        # No figures extracted and no primary, create preview of first page
        return create_pdf_screenshot(
            paper,
            skip_feed_refresh_extraction_check=skip_feed_refresh_extraction_check,
        )

    try:
        service = BedrockPrimaryImageService()
        selected_figure_id, best_score = service.select_primary_image(
            paper_title=paper.title or "",
            paper_abstract=paper.abstract or "",
            figures=list(figures),
        )

        # Check if we should use preview instead
        should_use_preview = False
        if not selected_figure_id:
            # No figure selected
            should_use_preview = True
            logger.info(f"No figure selected for paper {paper_id}, will use preview")
        elif best_score is not None and best_score < MIN_PRIMARY_SCORE_THRESHOLD:
            # Score too low
            should_use_preview = True
            logger.info(
                f"Best figure score {best_score}% below threshold "
                f"{MIN_PRIMARY_SCORE_THRESHOLD}% for paper {paper_id}, "
                f"will use preview"
            )

        if should_use_preview:
            # Create preview of first page
            preview_created = create_pdf_screenshot(
                paper,
                skip_feed_refresh_extraction_check=skip_feed_refresh_extraction_check,
            )
            if preview_created:
                logger.info(f"Created preview as primary image for paper {paper_id}")
                return True
            else:
                logger.warning(f"Failed to create preview for paper {paper_id}")
                return False
        elif selected_figure_id:
            # Update is_primary flags
            Figure.objects.filter(paper=paper).update(is_primary=False)
            Figure.objects.filter(id=selected_figure_id).update(is_primary=True)

            # Generate thumbnail for the selected primary figure
            selected_figure = Figure.objects.get(id=selected_figure_id)
            generate_thumbnail_for_figure(selected_figure)

            from feed.tasks import refresh_feed_entries_for_objects

            Paper = apps.get_model("paper.Paper")
            paper_content_type = ContentType.objects.get_for_model(Paper)
            refresh_feed_entries_for_objects.delay(
                paper.id,
                paper_content_type.id,
                skip_figure_extraction=skip_feed_refresh_extraction_check,
            )

            logger.info(
                f"Selected primary image {selected_figure_id} "
                f"(score: {best_score}%) for paper {paper_id}"
            )
            return True
        else:
            logger.warning(f"No figure selected for paper {paper_id}")
            return False

    except Exception as e:
        logger.error(f"Error selecting primary image for paper {paper_id}: {e}")
        sentry.log_error(e)

        # Retry on failure
        if retry < 2:
            select_primary_image.apply_async(
                (paper.id, retry + 1),
                priority=5,
                countdown=60 * (retry + 1),
            )

        return False
