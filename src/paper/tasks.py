import codecs
import json
import logging
import os
import re
import shutil
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO
from json.decoder import JSONDecodeError
from subprocess import PIPE, run
from unicodedata import normalize
from urllib.parse import urlparse

import cloudscraper
import feedparser
import fitz
import requests
import twitter
from bs4 import BeautifulSoup
from celery import chain
from celery.decorators import periodic_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.task.schedules import crontab
from celery.utils.log import get_task_logger
from cloudscraper.exceptions import CloudflareChallengeError
from django.apps import apps
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.db.models import Q
from django.http.request import HttpRequest
from django.utils.text import slugify
from habanero import Crossref
from PIL import Image
from psycopg2.errors import UniqueViolation
from pytz import timezone as pytz_tz
from requests.exceptions import HTTPError
from rest_framework.request import Request

from discussion.models import Comment, Thread
from hub.utils import scopus_to_rh_map
from paper.exceptions import (
    CrossrefSearchError,
    DOINotFoundError,
    DuplicatePaperError,
    ManubotProcessingError,
)
from paper.utils import (
    IGNORE_PAPER_TITLES,
    check_crossref_title,
    check_pdf_title,
    clean_abstract,
    clean_dois,
    fitz_extract_figures,
    format_raw_authors,
    get_cache_key,
    get_crossref_results,
    get_csl_item,
    get_pdf_from_url,
    get_pdf_location_for_csl_item,
    get_redirect_url,
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
    QUEUE_PAPER_METADATA,
    QUEUE_PAPER_MISC,
    QUEUE_PULL_PAPERS,
    QUEUE_TWITTER,
    app,
)
from researchhub.settings import APP_ENV, PRODUCTION, STAGING
from researchhub_document.utils import update_unified_document_to_paper
from utils import sentry
from utils.arxiv.categories import (
    ARXIV_CATEGORIES,
    get_category_name,
    get_general_hub_name,
)
from utils.crossref import get_crossref_issued_date
from utils.http import check_url_contains_pdf
from utils.twitter import RATE_LIMIT_CODE, get_twitter_results, get_twitter_url_results

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_CACHES)
def celery_paper_reset_cache(paper_id):
    from paper.serializers import PaperSerializer

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)

    serializer = PaperSerializer(paper)
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
                user.set_probable_spammer()

        uploaded_by = paper.uploaded_by
        uploaded_by.set_probable_spammer()


@app.task(queue=QUEUE_PAPER_MISC)
def download_pdf(paper_id, retry=0):
    if retry > 3:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)
    paper_url = paper.url
    pdf_url = paper.pdf_url
    pdf_url_contains_pdf = check_url_contains_pdf(pdf_url)
    url = pdf_url or paper_url
    url_has_pdf = check_url_contains_pdf(paper_url) or pdf_url_contains_pdf
    oa_pdf_url = None

    if (paper_url or pdf_url) and not url_has_pdf:
        csl_item = get_csl_item(url)
        oa_result = get_pdf_location_for_csl_item(csl_item)
        if oa_result:
            oa_url_1 = oa_result.get("url", None)
            oa_url_2 = oa_result.get("url_for_pdf", None)
            oa_pdf_url = oa_url_1 or oa_url_2
            url = oa_pdf_url

    if (paper_url and url_has_pdf) or oa_pdf_url:
        try:
            pdf = get_pdf_from_url(url)
            filename = paper.url.split("/").pop()
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            paper.file.save(filename, pdf)
            paper.save(update_fields=["file"])
            paper.extract_pdf_preview(use_celery=True)
            paper.set_paper_completeness()
            celery_extract_pdf_sections.apply_async(
                (paper_id,), priority=5, countdown=15
            )
        except Exception as e:
            sentry.log_info(e)
            download_pdf.apply_async(
                (paper.id, retry + 1), priority=7, countdown=15 * (retry + 1)
            )


@app.task(queue=QUEUE_PAPER_MISC)
def add_references(paper_id):
    if paper_id is None:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)
    paper.add_references()


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
            pix = page.getPixmap(alpha=False)
            output_filename = f"{paper_id}-{page.number}.jpg"

            if not extracted_figures.filter(
                file__contains=output_filename, figure_type=Figure.PREVIEW
            ):
                img_buffer = BytesIO()
                img_buffer.write(pix.getImageData(output="jpg"))
                image = Image.open(img_buffer)
                image.save(img_buffer, "jpeg", quality=0)
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
def celery_extract_twitter_comments(paper_id):
    # TODO: Optimize this
    return

    if paper_id is None:
        return

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)
    url = paper.url
    if not url:
        return

    source = "twitter"
    try:

        results = get_twitter_url_results(url)
        for res in results:
            source_id = res.id_str
            username = res.user.screen_name
            text = res.full_text
            thread_user_profile_img = res.user.profile_image_url_https
            thread_created_date = res.created_at_in_seconds
            thread_created_date = datetime.fromtimestamp(
                thread_created_date, timezone.utc
            )

            thread_exists = Thread.objects.filter(
                external_metadata__source_id=source_id
            ).exists()

            if not thread_exists:
                external_thread_metadata = {
                    "source_id": source_id,
                    "username": username,
                    "picture": thread_user_profile_img,
                    "url": f"https://twitter.com/{username}/status/{source_id}",
                }
                thread = Thread.objects.create(
                    paper=paper,
                    source=source,
                    external_metadata=external_thread_metadata,
                    plain_text=text,
                )
                thread.created_date = thread_created_date
                thread.save()

                query = f"to:{username}"
                replies = get_twitter_results(query)
                for reply in replies:
                    reply_username = reply.user.screen_name
                    reply_id = reply.id_str
                    reply_text = reply.full_text
                    comment_user_img = reply.user.profile_image_url_https
                    comment_created_date = reply.created_at_in_seconds
                    comment_created_date = datetime.fromtimestamp(
                        comment_created_date, timezone.utc
                    )

                    reply_exists = Comment.objects.filter(
                        external_metadata__source_id=reply_id
                    ).exists()

                    if not reply_exists:
                        external_comment_metadata = {
                            "source_id": reply_id,
                            "username": reply_username,
                            "picture": comment_user_img,
                            "url": f"https://twitter.com/{reply_username}/status/{reply_id}",
                        }
                        comment = Comment.objects.create(
                            parent=thread,
                            source=source,
                            external_metadata=external_comment_metadata,
                            plain_text=reply_text,
                        )
                        comment.created_date = comment_created_date
                        comment.save()
    except twitter.TwitterError:
        # TODO: Do we want to push the call back to celery if it exceeds the
        # rate limit?
        return


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
                if not extracted_figures.filter(
                    file__contains=f.name, figure_type=Figure.FIGURE
                ):
                    Figure.objects.create(
                        file=File(f), paper=paper, figure_type=Figure.FIGURE
                    )
    except Exception as e:
        stdout = call_res.stdout.decode("utf8")
        message = f"{return_code}; {stdout}; "
        try:
            message += str(os.listdir(path))
        except Exception as e:
            message += str(os.listdir("/tmp/pdf_cermine")) + str(e)

        sentry.log_error(e, message=message)
    finally:
        shutil.rmtree(path)
        return True, return_code


@app.task(queue=QUEUE_TWITTER, ignore_result=False)
def celery_calculate_paper_twitter_score(paper_id, iteration=0):
    if paper_id is None or iteration > 2:
        return False

    Paper = apps.get_model("paper.Paper")
    paper = Paper.objects.get(id=paper_id)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0)

    title = paper.title
    if title:
        words_in_title = paper.title.split(" ")
        if len(words_in_title) <= 4:
            return False, "Probable spam paper"

    try:
        twitter_score = paper.calculate_twitter_score()
    except Exception as e:
        error_message = e.message[0]
        code = error_message["code"]
        if code != RATE_LIMIT_CODE:
            return False, str(e)

        uploaded_date = paper.uploaded_date
        if uploaded_date >= today:
            priority = 4
        else:
            priority = 7

        celery_calculate_paper_twitter_score.apply_async(
            (paper_id, iteration), priority=priority, countdown=420
        )
        return False, str(e)

    # Temporarily stopping next day twitter score updates
    # next_iteration = iteration + 1
    # celery_calculate_paper_twitter_score.apply_async(
    #     (paper_id, next_iteration),
    #     priority=7 - next_iteration,
    #     countdown=86400 * next_iteration
    # )
    score = paper.calculate_score()
    paper.score = score
    paper.save()

    if score > 0:
        paper.calculate_hot_score()
    paper_cache_key = get_cache_key("paper", paper.id)
    cache.delete(paper_cache_key)

    return True, score


@app.task(queue=QUEUE_PAPER_MISC)
def handle_duplicate_doi(new_paper, doi):
    Paper = apps.get_model("paper.Paper")
    original_paper = Paper.objects.filter(doi=doi).order_by("uploaded_date")[0]
    merge_paper_votes(original_paper, new_paper)
    merge_paper_threads(original_paper, new_paper)
    merge_paper_bulletpoints(original_paper, new_paper)
    new_paper.delete()


@periodic_task(run_every=crontab(minute=0, hour=0), priority=5, queue=QUEUE_HOT_SCORE)
def celery_update_hot_scores():
    Paper = apps.get_model("paper.Paper")
    start_date = datetime.now() - timedelta(days=4)
    papers = Paper.objects.filter(uploaded_date__gte=start_date, is_removed=False)
    for paper in papers.iterator():
        paper.calculate_hot_score()


@app.task(queue=QUEUE_CACHES)
def preload_trending_papers(hub_id, ordering, time_difference, context):
    from paper.serializers import HubPaperSerializer
    from paper.views import PaperViewSet

    initial_date = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
    end_date = datetime.now()
    if time_difference > 365:
        cache_pk = f"{hub_id}_{ordering}_all_time"
        start_date = datetime(year=2018, month=12, day=31, hour=7)
    elif time_difference == 365:
        cache_pk = f"{hub_id}_{ordering}_year"
        start_date = initial_date - timedelta(days=365)
    elif time_difference == 30 or time_difference == 31:
        cache_pk = f"{hub_id}_{ordering}_month"
        start_date = initial_date - timedelta(days=30)
    elif time_difference == 7:
        cache_pk = f"{hub_id}_{ordering}_week"
        start_date = initial_date - timedelta(days=7)
    else:
        start_date = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
        cache_pk = f"{hub_id}_{ordering}_today"

    query_string_ordering = "top_rated"
    if ordering == "removed":
        query_string_ordering = "removed"
    elif ordering == "-score":
        query_string_ordering = "top_rated"
    elif ordering == "-discussed":
        query_string_ordering = "most_discussed"
    elif ordering == "-uploaded_date":
        query_string_ordering = "newest"
    elif ordering == "-hot_score":
        query_string_ordering = "hot"

    request_path = "/api/paper/get_hub_papers/"
    if STAGING:
        http_host = "staging-backend.researchhub.com"
        protocol = "https"
    elif PRODUCTION:
        http_host = "backend.researchhub.com"
        protocol = "https"
    else:
        http_host = "localhost:8000"
        protocol = "http"

    start_date_timestamp = int(start_date.timestamp())
    end_date_timestamp = int(end_date.timestamp())
    query_string = (
        "page=1&start_date__gte={}&end_date__lte={}&ordering={}&hub_id={}&".format(
            start_date_timestamp, end_date_timestamp, query_string_ordering, hub_id
        )
    )
    http_meta = {
        "QUERY_STRING": query_string,
        "HTTP_HOST": http_host,
        "HTTP_X_FORWARDED_PROTO": protocol,
    }

    cache_key_hub = get_cache_key("hub", cache_pk)
    paper_view = PaperViewSet()
    http_req = HttpRequest()
    http_req.META = http_meta
    http_req.path = request_path
    req = Request(http_req)
    paper_view.request = req

    papers = paper_view._get_filtered_papers(hub_id, ordering).filter(
        uploaded_by_id__isnull=False
    )
    order_papers = paper_view.calculate_paper_ordering(
        papers, ordering, start_date, end_date
    )
    page = paper_view.paginate_queryset(order_papers)
    serializer = HubPaperSerializer(page, many=True, context=context)
    serializer_data = serializer.data

    paginated_response = paper_view.get_paginated_response(
        {"data": serializer_data, "no_results": False, "feed_type": "all"}
    )

    cache_key_hub = get_cache_key("hub", cache_pk)
    cache.set(cache_key_hub, paginated_response.data, timeout=None)

    return paginated_response.data


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
        uploaded_date__gte=start_date,
        uploaded_date__lte=end_date,
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


# ARXIV Download Constants
RESULTS_PER_ITERATION = (
    50  # default is 10, if this goes too high like >=100 it seems to fail too often
)
WAIT_TIME = 3  # The docs recommend 3 seconds between queries
RETRY_WAIT = 8
RETRY_MAX = 20  # It fails a lot so retry a bunch
NUM_DUP_STOP = 30  # Number of dups to hit before determining we're done
BASE_URL = "http://export.arxiv.org/api/query?"

# Pull Daily (arxiv updates 20:00 EST)
# @periodic_task(
#     run_every=crontab(minute=0, hour='*/2'),
#     priority=2,
#     queue=QUEUE_PULL_PAPERS,
# )
def pull_papers(start=0, force=False):
    # Temporarily disabling autopull
    return

    if not PRODUCTION and not force:
        return

    logger.info("Pulling Papers")

    Paper = apps.get_model("paper.Paper")
    Summary = apps.get_model("summary.Summary")
    Hub = apps.get_model("hub.Hub")

    # Namespaces don't quite work with the feedparser, so hack them in
    feedparser.namespaces._base.Namespace.supported_namespaces[
        "http://a9.com/-/spec/opensearch/1.1/"
    ] = "opensearch"
    feedparser.namespaces._base.Namespace.supported_namespaces[
        "http://arxiv.org/schemas/atom"
    ] = "arxiv"

    # Code Inspired from https://static.arxiv.org/static/arxiv.marxdown/0.1/help/api/examples/python_arXiv_parsing_example.txt
    # Original Author: Julius B. Lucks

    # All categories
    search_query = "+OR+".join(["cat:" + cat for cat in ARXIV_CATEGORIES])
    sortBy = "submittedDate"
    sortOrder = "descending"

    i = start
    num_retries = 0
    dups = 0
    twitter_score_priority = 4
    while True:
        logger.info("Entries: %i - %i" % (i, i + RESULTS_PER_ITERATION))

        query = "search_query=%s&start=%i&max_results=%i&sortBy=%s&sortOrder=%s&" % (
            search_query,
            i,
            RESULTS_PER_ITERATION,
            sortBy,
            sortOrder,
        )

        with urllib.request.urlopen(BASE_URL + query) as url:
            response = url.read()
            feed = feedparser.parse(response)
            # If failed to fetch and we're not at the end retry until the limit
            if url.getcode() != 200:
                if num_retries < RETRY_MAX and i < int(
                    feed.feed.opensearch_totalresults
                ):
                    num_retries += 1
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    return

            if i == start:
                logger.info(f"Total results: {feed.feed.opensearch_totalresults}")
                logger.info(f"Last updated: {feed.feed.updated}")

            # If no results and we're at the end or we've hit the retry limit give up
            if len(feed.entries) == 0:
                if num_retries < RETRY_MAX and i < int(
                    feed.feed.opensearch_totalresults
                ):
                    num_retries += 1
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    return

            # Run through each entry, and print out information
            for entry in feed.entries:
                num_retries = 0
                try:
                    title = entry.title
                    if title.lower() in IGNORE_PAPER_TITLES:
                        continue

                    paper, created = Paper.objects.get_or_create(url=entry.id)
                    if created:
                        paper.alternate_ids = {"arxiv": entry.id.split("/abs/")[-1]}
                        paper.title = title
                        paper.paper_title = title
                        paper.abstract = clean_abstract(entry.summary)
                        paper.paper_publish_date = entry.published.split("T")[0]
                        paper.external_source = "Arxiv"
                        paper.external_metadata = entry

                        authors = [entry.author]
                        authors += [author.name for author in entry.authors]
                        raw_authors = []

                        for author in authors:
                            full_name = author.split(" ")
                            if len(full_name) > 1:
                                raw_authors.append(
                                    {
                                        "first_name": full_name[0],
                                        "last_name": full_name[-1],
                                    }
                                )
                            else:
                                raw_authors.append(
                                    {"first_name": full_name, "last_name": ""}
                                )
                        paper.raw_authors = raw_authors

                        pdf_url = ""
                        csl = {}
                        for link in entry.links:
                            try:
                                if link.title == "pdf":
                                    try:
                                        pdf_url = get_redirect_url(link.href)
                                        if pdf_url:
                                            paper.pdf_url = pdf_url
                                            csl = get_csl_item(pdf_url)
                                            if csl:
                                                paper.csl_item = csl
                                    except Exception as e:
                                        sentry.log_error(e)
                                if link.title == "doi":
                                    paper.doi = link.href.split("doi.org/")[-1]
                            except AttributeError:
                                pass

                        if csl:
                            license = paper.get_license(save=False)
                            if license:
                                twitter_score_priority = 1
                                paper.pdf_license = license

                        paper.save()
                        paper.set_paper_completeness()
                        update_unified_document_to_paper(paper)

                        if pdf_url:
                            download_pdf.apply_async(
                                (paper.id,), priority=5, countdown=7
                            )

                        celery_calculate_paper_twitter_score.apply_async(
                            (paper.id,), priority=twitter_score_priority, countdown=15
                        )

                        add_orcid_authors.apply_async(
                            (paper.id,), priority=6, countdown=10
                        )

                        # If not published in the past week we're done
                        if Paper.objects.get(
                            pk=paper.id
                        ).paper_publish_date < datetime.now().date() - timedelta(
                            days=7
                        ):
                            return

                        # Arxiv Journal Ref
                        # try:
                        # journal_ref = entry.arxiv_journal_ref
                        # except AttributeError:
                        # journal_ref = 'No journal ref found'

                        # Arxiv Comment
                        # try:
                        # comment = entry.arxiv_comment
                        # except AttributeError:
                        # comment = 'No comment found'

                        # Arxiv Categories
                        # all_categories = [t['term'] for t in entry.tags]
                        try:
                            general_hub = get_general_hub_name(
                                entry.arxiv_primary_category["term"]
                            )
                            if general_hub:
                                hub = Hub.objects.filter(
                                    name__iexact=general_hub
                                ).first()
                                if hub:
                                    paper.hubs.add(hub)

                            specific_hub = get_category_name(
                                entry.arxiv_primary_category["term"]
                            )
                            if specific_hub:
                                shub = Hub.objects.filter(
                                    name__iexact=general_hub
                                ).first()
                                if shub:
                                    paper.hubs.add(shub)
                        except AttributeError:
                            pass
                    else:
                        # if we've reach the max dups then we're done
                        if dups > NUM_DUP_STOP:
                            return
                        else:
                            dups += 1
                except Exception as e:
                    sentry.log_error(e)

        # Rate limit
        time.sleep(WAIT_TIME)

        i += RESULTS_PER_ITERATION


# Crossref Download Constants
RESULTS_PER_ITERATION = 200
WAIT_TIME = 2
RETRY_WAIT = 8
RETRY_MAX = 20
NUM_DUP_STOP = 30

# Pull Daily
# @periodic_task(
#     run_every=crontab(minute=0, hour='*/6'),
#     priority=1,
#     queue=QUEUE_PULL_PAPERS
# )
def pull_crossref_papers(start=0, force=False):
    # Temporarily disabling autopull
    return

    if not PRODUCTION and not force:
        return

    logger.info("Pulling Crossref Papers")
    sentry.log_info("Pulling Crossref Papers")

    Paper = apps.get_model("paper.Paper")
    Hub = apps.get_model("hub.Hub")

    cr = Crossref()

    twitter_score_priority = 1
    num_retries = 0
    num_duplicates = 0

    offset = 0
    today = datetime.now().date()
    start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    filters = {
        "type": "journal-article",
        "from-created-date": start_date,
        "until-created-date": end_date,
        "from-index-date": start_date,
        "until-index-date": end_date,
    }

    while True:
        try:
            try:
                results = cr.works(
                    filter=filters,
                    limit=RESULTS_PER_ITERATION,
                    sort="issued",
                    order="desc",
                    offset=offset,
                )
            except Exception as e:
                if num_retries < RETRY_MAX:
                    num_retries += 1
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    sentry.log_error(e)
                    return

            items = results["message"]["items"]
            total_results = results["message"]["total-results"]
            if total_results == 0 or len(items) == 0:
                if num_retries < RETRY_MAX:
                    num_retries += 1
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    sentry.log_info("No Crossref results found")
                    return

            for item in items:
                num_retries = 0
                try:
                    title = item["title"][0]
                    if title.lower() in IGNORE_PAPER_TITLES:
                        continue

                    paper, created = Paper.objects.get_or_create(doi=item["DOI"])
                    if created:
                        paper.title = title
                        paper.paper_title = title
                        paper.slug = slugify(title)
                        paper.doi = item["DOI"]
                        paper.url = item["URL"]
                        paper.paper_publish_date = get_crossref_issued_date(item)
                        paper.retrieved_from_external_source = True
                        paper.external_metadata = item
                        external_source = item.get("container-title", ["Crossref"])[0]
                        if type(external_source) is list:
                            external_source = external_source[0]

                        paper.external_source = external_source
                        paper.publication_type = item["type"]
                        if "abstract" in item:
                            paper.abstract = clean_abstract(item["abstract"])
                        else:
                            csl = {}
                            try:
                                csl = get_csl_item(item["URL"])
                                if csl:
                                    paper.csl_item = csl
                                    abstract = csl.get("abstract", None)
                                    if abstract:
                                        paper.abstract = abstract
                            except Exception as e:
                                sentry.log_error(e)

                        if "author" in item:
                            paper.raw_authors = {}
                            raw_authors = []
                            for i, author in enumerate(item["author"]):
                                given = author.get("given")
                                family = author.get("family")
                                if given and family:
                                    raw_authors.append(
                                        {"last_name": family, "first_name": given}
                                    )
                            if raw_authors:
                                paper.raw_authors = raw_authors

                        pdf_url = ""
                        if "link" in item and item["link"]:
                            try:
                                pdf_url = get_redirect_url(item["link"][0]["URL"])
                            except Exception as e:
                                sentry.log_error(e)
                            if check_url_contains_pdf(pdf_url):
                                paper.pdf_url = pdf_url

                        if "subject" in item:
                            for subject_name in item["subject"]:
                                rh_key = scopus_to_rh_map[subject_name]
                                hub = Hub.objects.filter(name__iexact=rh_key).first()
                                if hub:
                                    paper.hubs.add(hub)

                        if csl:
                            license = paper.get_license(save=False)
                            if license:
                                twitter_score_priority = 1
                                paper.pdf_license = license

                        paper.save()
                        paper.set_paper_completeness()
                        update_unified_document_to_paper(paper)

                        celery_calculate_paper_twitter_score.apply_async(
                            (paper.id,), priority=twitter_score_priority, countdown=15
                        )
                        add_orcid_authors.apply_async(
                            (paper.id,), priority=6, countdown=10
                        )

                        if pdf_url:
                            download_pdf.apply_async(
                                (paper.id,), priority=5, countdown=7
                            )
                    else:
                        num_duplicates += 1
                except Exception as e:
                    sentry.log_error(e)

            offset += RESULTS_PER_ITERATION
            time.sleep(WAIT_TIME)
        except Exception as e:
            sentry.log_error(e, message=f"Total Results: {total_results}")

    info = f"""
        Crossref Duplicates Detected: {num_duplicates}\n
        Total Crossref pull: {total_results}
    """
    sentry.log_info(info)
    return total_results


@app.task(bind=True, queue=QUEUE_PAPER_METADATA)
def celery_process_paper(self, submission_id):
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    paper_submission = PaperSubmission.objects.get(id=submission_id)
    paper_submission.set_processing_status()
    paper_submission.notify_status()
    uploaded_by = paper_submission.uploaded_by
    url = paper_submission.url
    doi = paper_submission.doi
    celery_data = {"url": url, "uploaded_by_id": uploaded_by.id}
    args = (
        celery_data,
        submission_id,
    )

    if doi:
        celery_data["dois"] = [doi]

    tasks = []
    if url:
        tasks.extend(
            [
                celery_get_doi.s().set(countdown=1),
                celery_manubot_doi.s().set(countdown=1),
            ]
        )

    # Specific Crossref bypass for Manubot (Arxiv links)
    parsed_url = urlparse(url)
    if parsed_url.netloc == "arxiv.org":
        tasks.extend([celery_manubot.s().set(countdown=1)])
    else:
        tasks.extend([celery_crossref.s().set(countdown=1)])

    tasks.extend([celery_create_paper.s().set(countdown=1)])

    chain(*tasks).apply_async(
        (args,),
        countdown=1,
        priority=1,
        link_error=celery_handle_paper_processing_errors.s(),
        soft_time_limit=60 * 2,
    )


@app.task(bind=True, queue=QUEUE_PAPER_METADATA)
def celery_get_doi(self, celery_data):
    paper_data, submission_id = celery_data
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    try:
        paper_submission = PaperSubmission.objects.get(id=submission_id)
        paper_submission.set_processing_doi_status()
        paper_submission.notify_status()

        url = paper_data["url"]
        parsed_url = urlparse(url)
        scraper = cloudscraper.create_scraper()
        res = scraper.get(url)
        status_code = res.status_code
        if status_code >= 200 and status_code < 400:
            content = BeautifulSoup(res.content, "lxml")
            dois = re.findall(
                r"10.\d{4,9}\/[-._;()\/:a-zA-Z0-9].+?(?=[\";%<>\?#&])", str(content)
            )
            dois = list(map(str.strip, dois))
            dois = clean_dois(parsed_url, dois)

            doi_counter = Counter(dois)
            paper_data["dois"] = [doi for doi, _ in doi_counter.most_common(1)]
            return celery_data
    except CloudflareChallengeError as e:
        sentry.log_info(e)
        return celery_data
    except Exception as e:
        raise e
    return celery_data


@app.task(bind=True, queue=QUEUE_PAPER_METADATA)
def celery_manubot_doi(self, celery_data):
    paper_data, submission_id = celery_data
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    try:
        paper_submission = PaperSubmission.objects.get(id=submission_id)
        paper_submission.set_manubot_status()
        paper_submission.notify_status()

        doi_exists = paper_data.get("dois", None)
        if doi_exists:
            return celery_data

        url = paper_data["url"]
        csl_item = get_csl_item(url)
        doi = csl_item.get("DOI", None)
        if doi:
            paper_data["dois"] = [doi]
        return celery_data
    except ManubotProcessingError:
        return celery_data
    except Exception as e:
        raise e


@app.task(bind=True, queue=QUEUE_PAPER_METADATA)
def celery_manubot(self, celery_data):
    paper_data, submission_id = celery_data
    Paper = apps.get_model("paper.Paper")
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    try:
        paper_submission = PaperSubmission.objects.get(id=submission_id)
        paper_submission.set_manubot_status()
        paper_submission.notify_status()

        paper_data.pop("dois")
        url = paper_data["url"]
        csl_item = get_csl_item(url)
        doi = csl_item.get("DOI", None)
        identifier = csl_item.get("id", None)

        # DOI duplicate check
        if doi:
            doi_paper_check = Paper.objects.filter(doi=doi)
            if doi_paper_check.exists():
                paper_submission.set_duplicate_status()
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)
        else:
            doi = identifier

        paper_submission.doi = doi
        paper_submission.save()

        # Url duplicate check
        oa_pdf_location = get_pdf_location_for_csl_item(csl_item)
        csl_item["oa_pdf_location"] = oa_pdf_location
        urls = [url]
        if oa_pdf_location:
            oa_url = oa_pdf_location.get("url", [])
            oa_landing_page_url = oa_pdf_location.get("url_for_landing_page", [])
            oa_pdf_url = oa_pdf_location.get("url_for_pdf", [])

            urls.extend(oa_url)
            urls.extend(oa_landing_page_url)
            urls.extend(oa_pdf_url)

        url_paper_check = Paper.objects.filter(Q(url__in=urls) | Q(pdf_url__in=urls))
        if url_paper_check.exists():
            paper_submission.set_duplicate_status()
            duplicate_ids = url_paper_check.values_list("id", flat=True)
            raise DuplicatePaperError(f"Duplicate URL: {urls}", duplicate_ids)

        # Cleaning csl data
        cleaned_title = csl_item.get("title", "").strip()
        abstract = csl_item.get("abstract", "")
        cleaned_abstract = clean_abstract(abstract)
        publish_date = csl_item.get_date("issued", fill=True)
        raw_authors = csl_item.get("author", [])
        raw_authors = format_raw_authors(raw_authors)
        paper_data = {
            **paper_data,
            "abstract": cleaned_abstract,
            "csl_item": csl_item,
            "doi": doi,
            "paper_publish_date": publish_date,
            "raw_authors": raw_authors,
            "title": cleaned_title,
        }

        if oa_pdf_location:
            if oa_pdf_url:
                paper_data["pdf_url"] = oa_pdf_url

            license = oa_pdf_location.get("license", None)
            paper_data["pdf_license"] = license

        return (paper_data, submission_id)
    except DuplicatePaperError as e:
        raise e
    except ManubotProcessingError as e:
        raise e
    except Exception as e:
        raise e


@app.task(bind=True, queue=QUEUE_PAPER_METADATA)
def celery_crossref(self, celery_data):
    paper_data, submission_id = celery_data
    Paper = apps.get_model("paper.Paper")
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    try:
        paper_submission = PaperSubmission.objects.get(id=submission_id)
        paper_submission.set_crossref_status()
        paper_submission.notify_status()

        dois = paper_data.pop("dois", [])

        if not dois:
            raise DOINotFoundError("No DOIs were found")

        cr = Crossref()
        results = None
        for doi in dois:
            try:
                params = {
                    "filters": {"type": "journal-article"},
                    "ids": [doi],
                }
                results = cr.works(**params).get("message")
                paper_data["doi"] = doi
                paper_submission.doi = doi
                paper_submission.save()
                break
            except (HTTPError, JSONDecodeError) as e:
                sentry.log_error(e)
                print(e)
                pass

        if results:
            # Duplicate DOI check
            doi = paper_data["doi"]
            doi_paper_check = Paper.objects.filter(doi=doi)
            if doi_paper_check.exists():
                paper_submission.set_duplicate_status()
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)

            abstract = clean_abstract(results.get("abstract", ""))
            paper_data["abstract"] = abstract
            raw_authors = results.get("author", [])
            paper_data["raw_authors"] = format_raw_authors(raw_authors)
            title = normalize("NFKD", results.get("title", [])[0])
            paper_data["title"] = title
            paper_data["paper_title"] = title
            return celery_data
        raise CrossrefSearchError(f"Could not find Crossref data for: {dois}")
    except DOINotFoundError as e:
        raise e
    except DuplicatePaperError as e:
        raise e
    except Exception as e:
        raise e


@app.task(bind=True, queue=QUEUE_PAPER_METADATA)
def celery_create_paper(self, celery_data):
    from reputation.tasks import create_contribution

    paper_data, submission_id = celery_data
    Paper = apps.get_model("paper.Paper")
    PaperSubmission = apps.get_model("paper.PaperSubmission")
    Vote = apps.get_model("paper.Vote")
    Contribution = apps.get_model("reputation.Contribution")

    try:
        paper = Paper(**paper_data)
        paper.full_clean()
        paper.save()
        paper_id = paper.id

        paper_submission = PaperSubmission.objects.get(id=submission_id)
        paper_submission.set_complete_status(save=False)
        paper_submission.paper = paper
        paper_submission.save()

        uploaded_by = paper_submission.uploaded_by
        Vote.objects.create(paper=paper, created_by=uploaded_by, vote_type=Vote.UPVOTE)
        download_pdf.apply_async((paper_id,), priority=3, countdown=5)
        add_orcid_authors.apply_async((paper_id,), priority=5, countdown=5)
        create_contribution.apply_async(
            (
                Contribution.SUBMITTER,
                {"app_label": "paper", "model": "paper"},
                uploaded_by.id,
                paper.unified_document.id,
                paper_id,
            ),
            priority=2,
            countdown=3,
        )
        paper_submission.notify_status()
        return paper_id
    except ValidationError as e:
        raise e
    except Exception as e:
        raise e


@app.task(queue=QUEUE_PAPER_METADATA)
def celery_handle_paper_processing_errors(request, exc, traceback):
    try:
        sentry.log_error(exc)

        extra_metadata = {}
        PaperSubmission = apps.get_model("paper.PaperSubmission")
        args = request.args[0]
        _, submission_id = args
        paper_submission = PaperSubmission.objects.get(id=submission_id)

        if isinstance(exc, DuplicatePaperError):
            duplicate_ids = exc.args[1]
            extra_metadata["duplicate_ids"] = list(duplicate_ids)
            paper_submission.set_duplicate_status()
        elif isinstance(exc, SoftTimeLimitExceeded):
            paper_submission.set_failed_timeout_status()
        elif isinstance(exc, DOINotFoundError):
            paper_submission.set_failed_doi_status()
        else:
            paper_submission.set_failed_status()

        paper_submission.notify_status(**extra_metadata)
    except Exception as e:
        sentry.log_error(e, exc)

    return
