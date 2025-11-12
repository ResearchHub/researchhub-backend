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
        for vote in paper.votes.all():
            if vote.vote_type == 1:
                user = vote.created_by

        uploaded_by = paper.uploaded_by
        uploaded_by.set_probable_spammer()


@app.task(queue=QUEUE_PAPER_MISC, rate_limit="10/m")
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
    if external_source != "biorxiv":
        return url

    token = settings.SCRAPER_TOKEN
    if not token:
        return url

    target_url = urllib.parse.quote(url)
    return f"https://app.scrapingbee.com/api/v1/?api_key={token}&url={target_url}"


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
