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

from paper.ingestion.pipeline import (  # noqa: F401
    fetch_all_papers,
    fetch_papers_from_source,
    process_batch_task,
)
from paper.ingestion.tasks import update_recent_papers_with_metrics  # noqa: F401
from paper.utils import download_pdf_from_url, get_cache_key
from researchhub.celery import QUEUE_PAPER_MISC, app
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
            url = _create_download_url(pdf_url, paper.external_source)
            pdf = download_pdf_from_url(url)
            paper.file.save(pdf.name, pdf, save=False)
            paper.save(update_fields=["file"])

            # Trigger figure extraction after successful PDF download
            extract_pdf_figures.apply_async((paper.id,), priority=6)

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


def _create_download_url(url: str, external_source: str) -> str:
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
def extract_pdf_figures(paper_id, retry=0):
    """
    Extract embedded figures from a PDF and save them as Figure objects.

    Args:
        paper_id: ID of the paper
        retry: Number of retry attempts
    """
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
            priority=6,
            countdown=10 * (retry + 1),
        )
        return False

    try:
        # Get PDF content
        file_url = file.url
        res = requests.get(file_url, timeout=60)
        res.raise_for_status()
        pdf_content = res.content

        # Extract figures using service
        from paper.services.figure_extraction_service import FigureExtractionService

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

        # Trigger primary image selection if figures were extracted
        if figures_created > 0:
            select_primary_image.apply_async((paper.id,), priority=5)

        return True

    except Exception as e:
        logger.error(f"Error extracting figures for paper {paper_id}: {e}")
        sentry.log_error(e)

        # Retry on failure
        if retry < 2:
            extract_pdf_figures.apply_async(
                (paper.id, retry + 1),
                priority=6,
                countdown=30 * (retry + 1),
            )

        return False


@app.task(queue=QUEUE_PAPER_MISC)
def select_primary_image(paper_id, retry=0):
    """
    Use AWS Bedrock to select the primary image from extracted figures.

    Args:
        paper_id: ID of the paper
        retry: Number of retry attempts
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

    # Get all extracted figures (not previews)
    figures = Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE).order_by(
        "created_date"
    )

    if not figures.exists():
        logger.info(
            f"No figures found for paper {paper_id}, skipping primary selection"
        )
        return False

    try:
        from paper.services.bedrock_primary_image_service import (
            BedrockPrimaryImageService,
        )

        service = BedrockPrimaryImageService()
        selected_figure_id = service.select_primary_image(
            paper_title=paper.title or "",
            paper_abstract=paper.abstract or "",
            figures=list(figures),
        )

        if selected_figure_id:
            # Update is_primary flags
            Figure.objects.filter(paper=paper).update(is_primary=False)
            Figure.objects.filter(id=selected_figure_id).update(is_primary=True)

            logger.info(
                f"Selected primary image {selected_figure_id} for paper {paper_id}"
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
