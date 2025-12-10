import urllib.parse
from io import BytesIO

import fitz
import requests
from celery.utils.log import get_task_logger
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from PIL import Image

from paper.constants.figure_selection_criteria import MIN_PRIMARY_SCORE_THRESHOLD
from paper.ingestion.pipeline import (  # noqa: F401
    fetch_all_papers,
    fetch_papers_from_source,
    process_batch_task,
)
from paper.ingestion.tasks import update_recent_papers_with_metrics  # noqa: F401
from paper.services.bedrock_primary_image_service import BedrockPrimaryImageService
from paper.services.figure_extraction_service import FigureExtractionService
from paper.utils import download_pdf_from_url, get_cache_key
from researchhub.celery import QUEUE_PAPER_MISC, app
from researchhub.settings import PRODUCTION
from utils import sentry

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PAPER_MISC)
def censored_paper_cleanup(paper_id):
    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.filter(id=paper_id).first()

    if not paper.is_removed:
        paper.is_removed = True
        paper.save()

    if paper:
        paper.votes.update(is_removed=True)

        uploaded_by = paper.uploaded_by
        uploaded_by.set_probable_spammer()


@app.task(queue=QUEUE_PAPER_MISC)
def download_pdf(paper_id, retry=0):
    if retry > 3:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)

    pdf_url = paper.pdf_url or paper.url

    if pdf_url:
        try:
            url = create_download_url(pdf_url, paper.external_source)
            pdf = download_pdf_from_url(url)
            paper.file.save(pdf.name, pdf, save=False)
            paper.save(update_fields=["file"])

            skip_primary = not PRODUCTION
            extract_pdf_figures.apply_async(
                (paper.id,), {"skip_primary_selection": skip_primary}, priority=6
            )

            return True
        except ValueError as e:
            logger.warning(f"No PDF at {url} - paper {paper_id}: {e}")
            sentry.log_info(f"No PDF at {url} - paper {paper_id}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Failed to download PDF {url} - paper {paper_id}: {e}")
            sentry.log_info(f"Failed to download PDF {url} - paper {paper_id}: {e}")
            download_pdf.apply_async(
                (paper.id, retry + 1), priority=7, countdown=15 * (retry + 1)
            )
            return False

    return False


def create_download_url(url: str, external_source: str) -> str:
    if external_source not in ["arxiv", "biorxiv"]:
        return url

    scraper_url = settings.SCRAPER_URL
    if not scraper_url:
        return url

    target_url = urllib.parse.quote(url)
    return f"{scraper_url.format(url=target_url)}"


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
                    file=file, paper=paper, figure_type=Figure.PREVIEW
                )
    except Exception as e:
        sentry.log_error(e)
    finally:
        cache_key = get_cache_key("figure", paper_id)
        cache.delete(cache_key)
    return True


@app.task(queue=QUEUE_PAPER_MISC)
def extract_pdf_figures(paper_id, retry=0, skip_primary_selection=False):
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
    if not file:
        logger.info(f"No PDF file exists for paper {paper_id}, retrying...")
        extract_pdf_figures.apply_async(
            (paper.id, retry + 1),
            {"skip_primary_selection": skip_primary_selection},
            priority=6,
            countdown=10 * (retry + 1),
        )
        return False

    try:
        # Get PDF content
        file_url = file.url
        logger.info(
            f"Fetching PDF for paper {paper_id} from URL: {file_url} "
            f"(file.name: {file.name})"
        )
        res = requests.get(file_url, timeout=60)
        res.raise_for_status()
        pdf_content = res.content
        logger.info(
            f"Successfully fetched PDF for paper {paper_id}: "
            f"{len(pdf_content)} bytes, content-type: {res.headers.get('content-type', 'unknown')}"
        )

        # Extract figures using service
        extraction_service = FigureExtractionService()
        extracted_figures = extraction_service.extract_figures_from_pdf(
            pdf_content, paper_id
        )

        # Save extracted figures to database
        figures_created = 0
        for content_file, metadata in extracted_figures:
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
                )
                figures_created += 1

        logger.info(
            f"Extracted {figures_created} new figures for paper {paper_id} "
            f"(total extracted: {len(extracted_figures)})"
        )

        # Clear cache
        cache_key = get_cache_key("figure", paper_id)
        cache.delete(cache_key)

        # Select primary image unless explicitly skipped
        if skip_primary_selection:
            # In dev/staging automatic flow, create preview instead
            create_pdf_screenshot(paper)
            logger.info(
                f"Skipping primary image selection (automatic flow, not production). "
                f"Created preview for paper {paper_id}"
            )
        else:
            select_primary_image.apply_async((paper.id,), priority=5)

        return True

    except Exception as e:
        logger.error(f"Error extracting figures for paper {paper_id}: {e}")
        sentry.log_error(e)

        # Retry on failure
        if retry < 2:
            extract_pdf_figures.apply_async(
                (paper.id, retry + 1),
                {"skip_primary_selection": skip_primary_selection},
                priority=6,
                countdown=30 * (retry + 1),
            )

        return False


def create_pdf_screenshot(paper) -> bool:
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

        # Create figure as PREVIEW type
        preview_figure = Figure.objects.create(
            file=content_file,
            paper=paper,
            figure_type=Figure.PREVIEW,
            is_primary=True,
        )

        # Clear any other primary flags
        Figure.objects.filter(paper=paper).exclude(id=preview_figure.id).update(
            is_primary=False
        )

        doc.close()

        logger.info(f"Created preview for paper {paper.id}: {output_filename}")
        return True

    except Exception as e:
        logger.error(f"Error creating preview for paper {paper.id}: {e}")
        sentry.log_error(e)
        return False


@app.task(queue=QUEUE_PAPER_MISC)
def select_primary_image(paper_id, retry=0):
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
        return create_pdf_screenshot(paper)

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
            preview_created = create_pdf_screenshot(paper)
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
