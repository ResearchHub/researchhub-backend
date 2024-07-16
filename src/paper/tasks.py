import codecs
import json
import logging
import math
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from subprocess import PIPE, run
from unicodedata import normalize

import arxiv
import feedparser
import fitz
import requests
from bs4 import BeautifulSoup
from celery.decorators import periodic_task
from celery.task.schedules import crontab
from celery.utils.log import get_task_logger
from django.apps import apps
from django.contrib.postgres.search import SearchQuery
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Q
from habanero import Crossref
from PIL import Image
from psycopg2.errors import UniqueViolation
from pytz import timezone as pytz_tz

from discussion.models import Comment, Thread
from hub.models import Hub
from paper.openalex_util import process_openalex_works
from paper.utils import (
    check_crossref_title,
    check_pdf_title,
    fitz_extract_figures,
    format_raw_authors,
    get_cache_key,
    get_crossref_results,
    get_csl_item,
    get_pdf_from_url,
    get_pdf_location_for_csl_item,
    merge_paper_bulletpoints,
    merge_paper_threads,
    merge_paper_votes,
    reset_paper_cache,
)
from purchase.models import Wallet
from researchhub.celery import (
    QUEUE_CACHES,
    QUEUE_CERMINE,
    QUEUE_EXTERNAL_REPORTING,
    QUEUE_HOT_SCORE,
    QUEUE_PAPER_MISC,
    QUEUE_PULL_PAPERS,
    app,
)
from researchhub.settings import APP_ENV, PRODUCTION
from researchhub_document.related_models.constants.filters import NEW
from researchhub_document.utils import reset_unified_document_cache
from tag.models import Concept
from utils import sentry
from utils.arxiv.categories import get_category_name
from utils.http import check_url_contains_pdf
from utils.openalex import OpenAlex
from utils.parsers import get_license_by_url, rebuild_sentence_from_inverted_index

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_CACHES)
def celery_paper_reset_cache(paper_id):
    from paper.serializers import DynamicPaperSerializer
    from paper.views.paper_views import PaperViewSet

    context = PaperViewSet()._get_paper_context()

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)
    serializer = DynamicPaperSerializer(
        paper,
        context=context,
        _include_fields=[
            "abstract_src_markdown",
            "abstract_src_type",
            "abstract_src",
            "abstract",
            "authors",
            "boost_amount",
            "bounties",
            "created_date",
            "discussion_count",
            "doi",
            "external_source",
            "file",
            "first_preview",
            "hubs",
            "id",
            "is_open_access",
            "oa_status",
            "paper_publish_date",
            "paper_title",
            "pdf_file_extract",
            "pdf_license",
            "pdf_url",
            "raw_authors",
            "score",
            "slug",
            "title",
            "unified_document",
            "uploaded_by",
            "uploaded_date",
            "uploaded_date",
            "url",
        ],
    )
    data = serializer.data

    cache_key = get_cache_key("paper", paper_id)
    reset_paper_cache(cache_key, data)
    return data


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
            # Commenting out paper cache
            # paper.reset_cache(use_celery=False)
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
        return

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
def add_orcid_authors(paper_id):
    if paper_id is None:
        return False, "No Paper Id"

    from utils.orcid import orcid_api

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)
    orcid_authors = []
    doi = paper.doi
    if doi is not None:
        orcid_authors = orcid_api.get_authors(doi=doi)

    arxiv_id = paper.alternate_ids.get("arxiv", None)
    if arxiv_id is not None and doi:
        orcid_authors = orcid_api.get_authors(arxiv=doi)

    if arxiv_id is not None:
        orcid_authors = orcid_api.get_authors(arxiv=arxiv_id)

    if len(orcid_authors) < 1:
        print("No authors to add")
        logging.info("Did not find paper identifier to give to ORCID API")
        return False, "No Authors Found"

    paper.authors.add(*orcid_authors)
    if orcid_authors:
        paper_cache_key = get_cache_key("paper", paper_id)
        cache.delete(paper_cache_key)
    for author in paper.authors.iterator():
        Wallet.objects.get_or_create(author=author)
    logging.info(f"Finished adding orcid authors to paper {paper.id}")
    return True


@app.task(queue=QUEUE_PAPER_MISC)
def add_orcid_authors_batch(paper_ids):
    paper_ids = [id for id in paper_ids if id is not None]

    from paper.models import Paper
    from utils.orcid import orcid_api

    papers = Paper.objects.filter(id__in=paper_ids).only("doi", "alternate_ids")

    for paper in papers:
        orcid_authors = []
        doi = paper.doi
        arxiv_id = (
            paper.alternate_ids.get("arxiv", None) if paper.alternate_ids else None
        )

        if doi is not None:
            orcid_authors = orcid_api.get_authors(doi=doi)

        if arxiv_id is not None and doi:
            orcid_authors = orcid_api.get_authors(arxiv=doi)

        if arxiv_id is not None:
            orcid_authors = orcid_api.get_authors(arxiv=arxiv_id)

        if len(orcid_authors) < 1:
            print("No authors to add")
            logging.info("Did not find paper identifier to give to ORCID API")
            continue  # skip to next paper

        paper.authors.add(*orcid_authors)
        if orcid_authors:
            paper_cache_key = get_cache_key("paper", paper.id)
            cache.delete(paper_cache_key)
        for author in paper.authors.iterator():
            Wallet.objects.get_or_create(author=author)

    return True


@app.task(queue=QUEUE_PAPER_MISC)
def celery_extract_figures(paper_id):
    if paper_id is None:
        return

    Paper = apps.get_model("paper.Paper")
    Figure = apps.get_model("paper.Figure")
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        return

    path = f"/tmp/figures/{paper_id}/"
    filename = f"{paper.id}.pdf"
    file_path = f"{path}{filename}"
    file_url = file.url

    if not os.path.isdir(path):
        os.mkdir(path)

    try:
        res = requests.get(file_url)
        with open(file_path, "wb+") as f:
            f.write(res.content)

        fitz_extract_figures(file_path)

        figures = os.listdir(path)
        if len(figures) == 1:  # Only the pdf exists
            args = [
                "java",
                "-jar",
                "pdffigures2-assembly-0.1.0.jar",
                file_path,
                "-m",
                path,
                "-d",
                path,
                "-e",
            ]
            call_res = run(args, stdout=PIPE, stderr=PIPE)
            figures = os.listdir(path)

        for extracted_figure in figures:
            extracted_figure_path = f"{path}{extracted_figure}"
            if ".png" in extracted_figure:
                with open(extracted_figure_path, "rb") as f:
                    extracted_figures = Figure.objects.filter(paper=paper)
                    if not extracted_figures.filter(
                        file__contains=f.name, figure_type=Figure.FIGURE
                    ):
                        Figure.objects.create(
                            file=File(f), paper=paper, figure_type=Figure.FIGURE
                        )
    except Exception as e:
        message = call_res.stdout.decode("utf8")
        sentry.log_error(e, message=message)
    finally:
        shutil.rmtree(path)
        cache_key = get_cache_key("figure", paper_id)
        cache.delete(cache_key)


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


@periodic_task(run_every=crontab(minute=0, hour=0), priority=5, queue=QUEUE_HOT_SCORE)
def celery_update_hot_scores():
    Paper = apps.get_model("paper.Paper")
    start_date = datetime.now() - timedelta(days=4)
    papers = Paper.objects.filter(created_date__gte=start_date, is_removed=False)
    for paper in papers.iterator():
        paper.calculate_hot_score()


@periodic_task(
    run_every=crontab(minute=50, hour=23),
    priority=2,
    queue=QUEUE_EXTERNAL_REPORTING,
)
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


@app.task(queue=QUEUE_PULL_PAPERS)
def pull_openalex_author_works(user_id, openalex_id):
    from paper.models import Paper
    from reputation.models import Contribution
    from reputation.tasks import create_contribution
    from researchhub_case.utils.author_claim_case_utils import reward_author_claim_case
    from user.models import User

    oa = OpenAlex()
    author_works = oa.get_data_from_id(openalex_id)

    for work in author_works:
        with transaction.atomic():
            try:
                doi = work.get("doi")
                if doi is None:
                    print(f"No Doi for result: {work}")
                    continue
                pure_doi = doi.split("doi.org/")[-1]

                primary_location = work.get("best_oa_location", None) or work.get(
                    "primary_location", {}
                )
                source = primary_location.get("source", {}) or {}
                oa = work.get("open_access", {})
                oa_pdf_url = oa.get("oa_url", None)
                url = primary_location.get("landing_page_url", None)
                raw_title = work.get("title", "") or ""
                title = normalize("NFKD", raw_title)
                raw_authors = work.get("authorships", [])
                concepts = work.get("concepts", [])
                abstract = rebuild_sentence_from_inverted_index(
                    work.get("abstract_inverted_index", {})
                )

                raw_authors = format_raw_authors(raw_authors)
                user = User.objects.get(id=user_id)
                author_profile = user.author_profile
                raw_author_to_be_removed = None
                for raw_author in raw_authors:
                    if (
                        raw_author.get("first_name", "").lower()
                        == user.first_name.lower()
                        and raw_author.get("last_name", "").lower()
                        == user.last_name.lower()
                    ):
                        raw_author_to_be_removed = raw_author

                if raw_author_to_be_removed:
                    raw_authors.remove(raw_author_to_be_removed)

                doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(pure_doi))
                url_paper_check = Paper.objects.filter(
                    Q(url_svf=SearchQuery(url)) | Q(pdf_url_svf=SearchQuery(oa_pdf_url))
                )
                if doi_paper_check.exists() or url_paper_check.exists():
                    # This skips over the current iteration
                    paper = doi_paper_check.first() or url_paper_check.first()
                    paper.authors.add(author_profile)
                    paper.raw_authors = raw_authors
                    paper.save(update_fields=("raw_authors",))
                    reward_author_claim_case(author_profile, paper)
                    print(f"Skipping paper with doi {pure_doi}")
                    continue

                data = {
                    "doi": pure_doi,
                    "url": url,
                    "raw_authors": raw_authors,
                    "title": title,
                    "paper_title": title,
                    "paper_publish_date": work.get("publication_date", None),
                    "is_open_access": oa.get("is_oa", None),
                    "oa_status": oa.get("oa_status", None),
                    "pdf_license": source.get("license", None),
                    "external_source": source.get("display_name", ""),
                    "abstract": abstract,
                    "open_alex_raw_json": work,
                    "score": 1,
                    "uploaded_by_id": user_id,
                }
                if oa_pdf_url and check_url_contains_pdf(oa_pdf_url):
                    data["pdf_url"] = oa_pdf_url

                paper = Paper(**data)
                paper.full_clean()
                paper.save()
                paper.authors.add(author_profile)

                create_contribution.apply_async(
                    (
                        Contribution.SUBMITTER,
                        {"app_label": "paper", "model": "paper"},
                        user_id,
                        paper.unified_document.id,
                        paper.id,
                    ),
                    priority=3,
                    countdown=5,
                )

                potential_hubs = []
                try:
                    for concept in concepts:
                        concept_openalex_id = concept.get("id")
                        display_name = concept.get("display_name")
                        concept_obj, created = Concept.objects.get_or_create(
                            openalex_id=concept_openalex_id, display_name=display_name
                        )
                        if created:
                            # This creates the hub if a new concept is created
                            concept_obj.save()

                        paper.unified_document.concepts.add(
                            concept,
                            through_defaults={
                                "relevancy_score": concept["score"],
                                "level": concept["level"],
                            },
                        )

                        hub = concept_obj.hub
                        potential_hubs.append(hub.id)
                except Exception as e:
                    sentry.log_error(e)

                paper.hubs.add(*potential_hubs)
                paper.unified_document.hubs.add(*potential_hubs)

                download_pdf.apply_async((paper.id,), priority=4, countdown=4)
            except Exception as e:
                sentry.log_error(e)

    reset_unified_document_cache(
        document_type=["paper"],
        filters=[NEW],
    )
    return True


@periodic_task(
    # run at 6:00 AM UTC (10:00 PM PST)
    run_every=crontab(minute=00, hour=6),
    priority=3,
    queue=QUEUE_PULL_PAPERS,
)
def pull_new_openalex_works(start_index=0, retry=0, paper_fetch_log_id=None):
    """
    Pull new works (papers) from OpenAlex.

    This looks complicated because we're trying to handle retries and logging.
    But simply:
    1. Get new works from OpenAlex in batches
    2. Kick-off a task to create/update papers for each work
    3. If we hit an error, retry the job from where we left off
    4. Log the results
    """
    if not PRODUCTION:
        return

    from paper.models import PaperFetchLog

    date_to_fetch_from = datetime.now() - timedelta(days=1)
    # if paper_fetch_log_id is provided, it means we're retrying
    # otherwise we're starting a new pull
    if paper_fetch_log_id is None:
        start_date = datetime.now()

        # figure out when we should start fetching from.
        # if we have an existing successful run, we start from the last successful run
        try:
            last_successful_run_log = (
                PaperFetchLog.objects.filter(
                    source=PaperFetchLog.OPENALEX,
                    fetch_type=PaperFetchLog.FETCH_NEW,
                    status=PaperFetchLog.SUCCESS,
                )
                .order_by("-started_date")
                .first()
            )

            if last_successful_run_log:
                date_to_fetch_from = last_successful_run_log.started_date
        except Exception as e:
            sentry.log_error(e, message="Failed to get last successful log")

        # check if there's a pending log within the last 24 hours
        # if there is, skip this run.
        # this is to prevent multiple runs from being queued at the same time,
        # since our celery setup sometimes triggers multiple runs
        try:
            pending_log = PaperFetchLog.objects.filter(
                source=PaperFetchLog.OPENALEX,
                fetch_type=PaperFetchLog.FETCH_NEW,
                status=PaperFetchLog.PENDING,
                started_date__gte=date_to_fetch_from,
            ).exists()

            if pending_log:
                return
        except Exception as e:
            sentry.log_error(e, message="Failed to get pending log")

        lg = PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=PaperFetchLog.FETCH_NEW,
            status=PaperFetchLog.PENDING,
            started_date=start_date,
            fetch_since_date=date_to_fetch_from,
        )
        paper_fetch_log_id = lg.id
        sentry.log_info(f"Starting New OpenAlex pull: {paper_fetch_log_id}")
    else:
        # if paper_fetch_log_id is provided, it means we're retrying
        # so we should get the last fetch date from the log
        try:
            last_successful_run_log = PaperFetchLog.objects.get(id=paper_fetch_log_id)
            date_to_fetch_from = last_successful_run_log.fetch_since_date
        except Exception as e:
            sentry.log_error(
                e, message=f"Failed to get last log for id {paper_fetch_log_id}"
            )
            # consider this a failed run
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.FAILED,
                completed_date=datetime.now(),
            )
            return False

        sentry.log_info(f"Retrying OpenAlex pull: {paper_fetch_log_id}")

    if retry > 2:  # too many retries
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.FAILED,
                completed_date=datetime.now(),
            )
        return False

    total_papers_processed = 0
    # openalex uses a cursor to paginate through results,
    # cursor is meant to point to the next page of results.
    # if next_cursor = "*", it means it's the first page,
    # if next_cursor = None, it means it's the last page,
    # otherwise it's a base64 encoded string
    next_cursor = "*"
    try:
        open_alex = OpenAlex()

        while True:
            works, next_cursor = open_alex.get_works(
                type="article", since_date=date_to_fetch_from, next_cursor=next_cursor
            )
            # if we've reached the end of the results, exit the loop
            if next_cursor is None or works is None or len(works) == 0:
                break

            # if we're starting from a specific index, skip until we reach that index
            works_to_process = None
            if total_papers_processed >= start_index:
                works_to_process = works
            elif total_papers_processed + len(works) >= start_index:
                works_to_process = works[start_index - total_papers_processed :]
            if works_to_process is not None:
                process_openalex_works(works_to_process)

            total_papers_processed += len(works)

        # done processing all works
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.SUCCESS,
                completed_date=datetime.now(),
                total_papers_processed=total_papers_processed,
            )
    except Exception as e:
        sentry.log_error(e, message="Failed to pull new works from OpenAlex, retrying")
        pull_new_openalex_works.apply_async(
            (total_papers_processed, retry + 1, paper_fetch_log_id),
            priority=4,
            countdown=10 + (retry * 2),
        )
        # update total_papers_processed in the log
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                total_papers_processed=total_papers_processed,
            )
        return False


@app.task(queue=QUEUE_PULL_PAPERS)
def pull_openalex_author_works_batch(
    openalex_ids, user_id_to_notify_after_completion=None
):
    from notification.models import Notification
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
        works, cursor = open_alex_api.get_works(openalex_ids=chunk)
        process_openalex_works(works)

    if user_id_to_notify_after_completion:
        user = User.objects.get(id=user_id_to_notify_after_completion)
        notification = Notification.objects.create(
            item=user,
            notification_type=Notification.PUBLICATIONS_ADDED,
            recipient=user,
            action_user=user,
        )

        notification.send_notification()
