import urllib.parse

from celery.utils.log import get_task_logger
from django.apps import apps
from django.conf import settings

from paper.ingestion.pipeline import (  # noqa: F401
    fetch_all_papers,
    fetch_papers_from_source,
    process_batch_task,
)
from paper.ingestion.tasks import (  # noqa: F401
    enrich_paper_with_bluesky_metrics,
    enrich_paper_with_github_metrics,
    enrich_paper_with_x_metrics,
    enrich_papers_with_openalex,
    update_recent_papers_with_bluesky_metrics,
    update_recent_papers_with_github_metrics,
    update_recent_papers_with_x_metrics,
)
from paper.utils import download_pdf_from_url
from researchhub.celery import QUEUE_PAPER_MISC, app

# from researchhub.settings import PRODUCTION
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

            # skip_primary = not PRODUCTION
            # extract_pdf_figures.apply_async(
            #     (paper.id,), {"skip_primary_selection": skip_primary}, priority=6
            # )
            from paper.tasks.figure_tasks import extract_pdf_figures

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


def create_download_url(url: str, external_source: str) -> str:
    if external_source not in ["arxiv", "biorxiv"]:
        return url

    scraper_url = settings.SCRAPER_URL
    if not scraper_url:
        return url

    target_url = urllib.parse.quote(url)
    return f"{scraper_url.format(url=target_url)}"
