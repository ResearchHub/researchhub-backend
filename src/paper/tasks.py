import codecs
import json
import os
import re
import shutil
from datetime import datetime, timedelta
from io import BytesIO
from subprocess import PIPE, run

import fitz
import requests
from bs4 import BeautifulSoup
from celery.exceptions import MaxRetriesExceededError
from celery.utils.log import get_task_logger
from django.apps import apps
from django.core.cache import cache
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.utils import timezone
from habanero import Crossref
from PIL import Image
from psycopg2.errors import UniqueViolation
from pytz import timezone as pytz_tz

from paper.openalex_util import process_openalex_works
from paper.utils import (
    check_crossref_title,
    check_pdf_title,
    get_cache_key,
    get_crossref_results,
    get_csl_item,
    get_pdf_from_url,
    get_pdf_location_for_csl_item,
    merge_paper_bulletpoints,
    merge_paper_threads,
    merge_paper_votes,
)
from researchhub.celery import QUEUE_CERMINE, QUEUE_PAPER_MISC, QUEUE_PULL_PAPERS, app
from researchhub.settings import APP_ENV, PRODUCTION, TESTING
from utils import sentry
from utils.http import check_url_contains_pdf
from utils.openalex import OpenAlex

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


@app.task(queue=QUEUE_PAPER_MISC)
def download_pdf(paper_id, retry=0):
    if retry > 3:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)

    paper_pdf_url = paper.pdf_url
    paper_url = paper.url
    paper_url_contains_pdf = check_url_contains_pdf(paper_url)
    pdf_url_contains_pdf = check_url_contains_pdf(paper_pdf_url)

    if pdf_url_contains_pdf or paper_url_contains_pdf:
        pdf_url = paper_pdf_url or paper_url
        try:
            pdf = get_pdf_from_url(pdf_url)
            filename = pdf_url.split("/").pop()
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            paper.file.save(filename, pdf)
            paper.save(update_fields=["file"])
            paper.extract_pdf_preview(use_celery=True)
            paper.set_paper_completeness()
            paper.compress_and_linearize_file()
            celery_extract_pdf_sections.apply_async(
                (paper_id,), priority=5, countdown=15
            )
            return True
        except Exception as e:
            sentry.log_info(e)
            download_pdf.apply_async(
                (paper.id, retry + 1), priority=7, countdown=15 * (retry + 1)
            )
            return False

    csl_item = None
    pdf_url = None
    if paper_url:
        csl_item = get_csl_item(paper_url)
    elif paper_pdf_url:
        csl_item = get_csl_item(paper_pdf_url)

    if csl_item:
        oa_result = get_pdf_location_for_csl_item(csl_item)
        if oa_result:
            oa_url_1 = oa_result.get("url", None)
            oa_url_2 = oa_result.get("url_for_pdf", None)
            oa_pdf_url = oa_url_1 or oa_url_2
            pdf_url = oa_pdf_url
            pdf_url_contains_pdf = check_url_contains_pdf(pdf_url)

            if pdf_url_contains_pdf:
                paper.pdf_url = pdf_url
                paper.save()
                download_pdf.apply_async(
                    (paper.id, retry + 1), priority=7, countdown=15 * (retry + 1)
                )
        return

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
                    file=file, paper=paper, figure_type=Figure.PREVIEW
                )
    except Exception as e:
        sentry.log_error(e)
    finally:
        cache_key = get_cache_key("figure", paper_id)
        cache.delete(cache_key)
    return True


@app.task(queue=QUEUE_PAPER_MISC)
def celery_extract_meta_data(paper_id, title, check_title):
    if paper_id is None:
        return

    Paper = apps.get_model("paper.Paper")
    date_format = "%Y-%m-%dT%H:%M:%SZ"
    paper = Paper.objects.get(id=paper_id)

    if check_title:
        has_title = check_pdf_title(title, paper.file)
        if not has_title:
            return

    best_matching_result = get_crossref_results(title, index=1)[0]

    try:
        if "title" in best_matching_result:
            crossref_title = best_matching_result.get("title", [""])[0]
        else:
            crossref_title = best_matching_result.get("container-title", [""])
            crossref_title = crossref_title[0]

        similar_title = check_crossref_title(title, crossref_title)

        if not similar_title:
            return

        if not paper.doi:
            doi = best_matching_result.get("DOI", paper.doi)
            paper.doi = doi

        url = best_matching_result.get("URL", None)
        publish_date = best_matching_result["created"]["date-time"]
        publish_date = datetime.strptime(publish_date, date_format).date()
        tagline = best_matching_result.get("abstract", "")
        tagline = re.sub(r"<[^<]+>", "", tagline)  # Removing any jat xml tags

        paper.url = url
        paper.paper_publish_date = publish_date

        if not paper.tagline:
            paper.tagline = tagline

        paper_cache_key = get_cache_key("paper", paper_id)
        cache.delete(paper_cache_key)

        paper.check_doi()
        paper.save()
    except (UniqueViolation, IntegrityError) as e:
        sentry.log_info(e)
    except Exception as e:
        sentry.log_info(e)


@app.task(queue=QUEUE_PAPER_MISC)
def celery_get_paper_citation_count(paper_id, doi):
    if not doi:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)

    cr = Crossref()
    filters = {"type": "journal-article", "doi": doi}
    res = cr.works(filter=filters)

    result_count = res["message"]["total-results"]
    if result_count == 0:
        return

    citation_count = 0
    for item in res["message"]["items"]:
        keys = item.keys()
        if "DOI" not in keys:
            continue
        if item["DOI"] != doi:
            continue

        if "is-referenced-by-count" in keys:
            citation_count += item["is-referenced-by-count"]

    paper.citations = citation_count
    paper.save()


@app.task(queue=QUEUE_CERMINE)
def celery_extract_pdf_sections(paper_id):
    if paper_id is None:
        return False, "No Paper Id"

    Paper = apps.get_model("paper.Paper")
    Figure = apps.get_model("paper.Figure")
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        return False, "No Paper File"

    path = f"/tmp/pdf_cermine/{paper_id}/"
    filename = f"{paper_id}.pdf"
    extract_filename = f"{paper_id}.html"
    file_path = f"{path}{filename}"
    extract_file_path = f"{path}{paper_id}.cermxml"
    images_path = f"{path}{paper_id}.images"
    file_url = file.url
    return_code = -1

    if not os.path.isdir(path):
        os.mkdir(path)

    try:
        res = requests.get(file_url)
        with open(file_path, "wb+") as f:
            f.write(res.content)

        args = [
            "java",
            "-cp",
            "cermine-impl-1.13-jar-with-dependencies.jar",
            "pl.edu.icm.cermine.ContentExtractor",
            "-path",
            path,
        ]
        call_res = run(args, stdout=PIPE, stderr=PIPE)
        return_code = call_res.returncode

        with codecs.open(extract_file_path, "rb") as f:
            soup = BeautifulSoup(f, "lxml")
            paper.pdf_file_extract.save(extract_filename, ContentFile(soup.encode()))
        paper.save()

        figures = os.listdir(images_path)
        for extracted_figure in figures:
            extracted_figure_path = f"{images_path}/{extracted_figure}"
            with open(extracted_figure_path, "rb") as f:
                extracted_figures = Figure.objects.filter(paper=paper)
                split_file_name = f.name.split("/")
                file_name = split_file_name[-1]
                if not extracted_figures.filter(
                    file__contains=file_name, figure_type=Figure.FIGURE
                ):
                    Figure.objects.create(
                        file=File(f, name=file_name),
                        paper=paper,
                        figure_type=Figure.FIGURE,
                    )
    except Exception as e:
        stdout = call_res.stdout.decode("utf8")
        message = f"{return_code}; {stdout}; "
        try:
            message += str(os.listdir(path))
        except Exception as e:
            message += str(os.listdir("/tmp/pdf_cermine")) + str(e)

        sentry.log_error(e, message=message)
        return False, return_code
    finally:
        shutil.rmtree(path)
        return True, return_code


@app.task(queue=QUEUE_PAPER_MISC)
def handle_duplicate_doi(new_paper, doi):
    Paper = apps.get_model("paper.Paper")
    original_paper = Paper.objects.filter(doi=doi).order_by("created_date")[0]
    merge_paper_votes(original_paper, new_paper)
    merge_paper_threads(original_paper, new_paper)
    merge_paper_bulletpoints(original_paper, new_paper)
    new_paper.delete()


@app.task
def log_daily_uploads():
    from analytics.amplitude import Amplitude

    Paper = apps.get_model("paper.Paper")
    amp = Amplitude()
    url = amp.api_url
    key = amp.api_key

    today = datetime.now(tz=pytz_tz("US/Pacific"))
    start_date = today.replace(hour=0, minute=0, second=0)
    end_date = today.replace(hour=23, minute=59, second=59)
    papers = Paper.objects.filter(
        created_date__gte=start_date,
        created_date__lte=end_date,
        uploaded_by__isnull=True,
    )
    paper_count = papers.count()
    data = {
        "device_id": f"rh_{APP_ENV}",
        "event_type": "daily_autopull_count",
        "time": int(today.timestamp()),
        "insert_id": f"daily_autopull_{today.strftime('%Y-%m-%d')}",
        "event_properties": {"amount": paper_count},
    }
    hit = {"events": [data], "api_key": key}
    hit = json.dumps(hit)
    headers = {"Content-Type": "application/json", "Accept": "*/*"}
    request = requests.post(url, data=hit, headers=headers)
    return request.status_code, paper_count


@app.task(bind=True, max_retries=3)
def pull_new_openalex_works(self, retry=0, paper_fetch_log_id=None):
    from paper.models import PaperFetchLog

    return _pull_openalex_works(
        self, PaperFetchLog.FETCH_NEW, retry, paper_fetch_log_id
    )


@app.task(bind=True, max_retries=3)
def pull_updated_openalex_works(self, retry=0, paper_fetch_log_id=None):
    from paper.models import PaperFetchLog

    return _pull_openalex_works(
        self, PaperFetchLog.FETCH_UPDATE, retry, paper_fetch_log_id
    )


def _pull_openalex_works(self, fetch_type, retry=0, paper_fetch_log_id=None):
    from paper.models import PaperFetchLog

    """
    Pull works (papers) from OpenAlex.
    This looks complicated because we're trying to handle retries and logging.
    But simply:
    1. Get new or updated works from OpenAlex in batches
    2. Kick-off a task to create/update papers for each work
    3. If we hit an error, retry the job from where we left off
    4. Log the results
    """
    if not (PRODUCTION or TESTING):
        return

    date_to_fetch_from = timezone.now() - timedelta(days=1)
    # openalex uses a cursor to paginate through results,
    # cursor is meant to point to the next page of results.
    # if next_cursor = "*", it means it's the first page,
    # if next_cursor = None, it means it's the last page,
    # otherwise it's a base64 encoded string
    next_cursor = "*"

    total_papers_processed = 0

    # if paper_fetch_log_id is provided, it means we're retrying
    # otherwise we're starting a new pull
    if paper_fetch_log_id is None:
        start_date = timezone.now()

        # figure out when we should start fetching from.
        # if we have an existing successful run, we start from the last successful run
        try:
            last_successful_run_log = (
                PaperFetchLog.objects.filter(
                    source=PaperFetchLog.OPENALEX,
                    fetch_type=fetch_type,
                    status__in=[PaperFetchLog.SUCCESS, PaperFetchLog.FAILED],
                    journal=None,
                )
                .order_by("-started_date")
                .first()
            )
            if (
                last_successful_run_log
                and last_successful_run_log.status == PaperFetchLog.SUCCESS
            ):
                date_to_fetch_from = last_successful_run_log.started_date
            elif (
                last_successful_run_log
                and last_successful_run_log.status == PaperFetchLog.FAILED
            ):
                date_to_fetch_from = last_successful_run_log.fetch_since_date
                next_cursor = last_successful_run_log.next_cursor or "*"
        except Exception as e:
            sentry.log_error(e, message="Failed to get last successful or failed log")

        # check if there's a pending log within the last 24 hours
        # if there is, skip this run.
        # this is to prevent multiple runs from being queued at the same time,
        # since our celery setup sometimes triggers multiple runs
        try:
            pending_log = PaperFetchLog.objects.filter(
                source=PaperFetchLog.OPENALEX,
                fetch_type=fetch_type,
                status=PaperFetchLog.PENDING,
                started_date__gte=timezone.now() - timedelta(days=1),
                journal=None,
            ).exists()

            if pending_log:
                sentry.log_info(message="Pending log exists for updated works")
                return
        except Exception as e:
            sentry.log_error(e, message="Failed to get pending log")

        lg = PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=fetch_type,
            status=PaperFetchLog.PENDING,
            started_date=start_date,
            fetch_since_date=date_to_fetch_from,
            next_cursor=next_cursor,
        )
        paper_fetch_log_id = lg.id
        sentry.log_info(f"Starting New OpenAlex pull: {paper_fetch_log_id}")
    else:
        # if paper_fetch_log_id is provided, it means we're retrying
        # so we should get the last fetch date from the log
        try:
            last_successful_run_log = PaperFetchLog.objects.get(id=paper_fetch_log_id)
            date_to_fetch_from = last_successful_run_log.fetch_since_date
            total_papers_processed = last_successful_run_log.total_papers_processed or 0
        except Exception as e:
            sentry.log_error(
                e, message=f"Failed to get last log for id {paper_fetch_log_id}"
            )
            # consider this a failed run
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.FAILED,
                completed_date=timezone.now(),
            )
            return False

        sentry.log_info(f"Retrying OpenAlex pull: {paper_fetch_log_id}")

    try:
        open_alex = OpenAlex()

        while True:
            if fetch_type == PaperFetchLog.FETCH_NEW:
                works, next_cursor = open_alex.get_works(
                    types=["article"],
                    since_date=date_to_fetch_from,
                    next_cursor=next_cursor,
                )
            elif fetch_type == PaperFetchLog.FETCH_UPDATE:
                works, next_cursor = open_alex.get_works(
                    types=["article"],
                    from_updated_date=date_to_fetch_from,
                    next_cursor=next_cursor,
                )

            # if we've reached the end of the results, exit the loop
            if next_cursor is None or works is None or len(works) == 0:
                break

            process_openalex_works(works)

            total_papers_processed += len(works)

            # Update the log with the current state of the run
            if paper_fetch_log_id is not None:
                PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                    total_papers_processed=total_papers_processed,
                    next_cursor=next_cursor,
                )

        # done processing all works
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.SUCCESS,
                completed_date=timezone.now(),
                total_papers_processed=total_papers_processed,
                next_cursor=None,
            )
    except Exception as e:
        sentry.log_error(e, message="Failed to pull new works from OpenAlex, retrying")
        # update total_papers_processed in the log
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                total_papers_processed=total_papers_processed,
            )
        try:
            self.retry(
                args=[retry + 1, paper_fetch_log_id],
                exc=e,
                countdown=10 + (retry * 2),
            )
        except MaxRetriesExceededError:
            # We've exhausted all retries, update the log to FAILED
            if paper_fetch_log_id is not None:
                PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                    status=PaperFetchLog.FAILED,
                    completed_date=timezone.now(),
                )
            # Re-raise the original exception
            raise e

    return True


@app.task(queue=QUEUE_PULL_PAPERS)
def pull_openalex_author_works_batch(
    openalex_ids, user_id_to_notify_after_completion=None
):
    from notification.models import Notification
    from reputation.tasks import find_bounties_for_user_and_notify
    from user.related_models.user_model import User

    open_alex_api = OpenAlex()

    oa_ids = []
    for id_as_url in openalex_ids:
        just_id = id_as_url.split("/")[-1]
        oa_ids.append(just_id)

    # divide openalex_ids into chunks of 100
    # openalex api only allows 100 ids per request
    chunk_size = 100
    for i in range(0, len(oa_ids), chunk_size):
        chunk = oa_ids[i : i + chunk_size]
        works, _ = open_alex_api.get_works(openalex_ids=chunk)
        process_openalex_works(works)

    if user_id_to_notify_after_completion:
        user = User.objects.get(id=user_id_to_notify_after_completion)

        try:
            user.author_profile.calculate_hub_scores()
        except Exception as e:
            sentry.log_error(e)

        notification = Notification.objects.create(
            item=user,
            notification_type=Notification.PUBLICATIONS_ADDED,
            recipient=user,
            action_user=user,
        )

        notification.send_notification()

        if TESTING:
            find_bounties_for_user_and_notify(user.id)
        else:
            find_bounties_for_user_and_notify.apply_async(
                (user.id,), priority=3, countdown=1
            )
