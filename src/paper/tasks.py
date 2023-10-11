import codecs
import json
import logging
import math
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from io import BytesIO
from subprocess import PIPE, run
from unicodedata import normalize

import arxiv
import feedparser
import fitz
import requests
import twitter
from bs4 import BeautifulSoup
from celery.decorators import periodic_task
from celery.task.schedules import crontab
from celery.utils.log import get_task_logger
from django.apps import apps
from django.contrib.postgres.search import SearchQuery
from django.core.cache import cache
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
from utils import sentry
from utils.arxiv.categories import ALL_CATEGORIES, get_category_name
from utils.http import check_url_contains_pdf
from utils.openalex import OpenAlex
from utils.parsers import get_license_by_url, rebuild_sentence_from_inverted_index
from utils.twitter import get_twitter_results, get_twitter_url_results

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


# @periodic_task(
#     run_every=crontab(minute=0, hour="*/3"), priority=3, queue=QUEUE_PULL_PAPERS
# )
def pull_biorxiv_papers():
    sentry.log_info("Starting Biorxiv pull")

    from paper.models import Paper

    biorxiv_id = "https://openalex.org/S4306402567"
    today = datetime.now(tz=pytz_tz("US/Pacific")).strftime("%Y-%m-%d")
    open_alex = OpenAlex()
    biorxiv_works = open_alex.get_data_from_source(biorxiv_id, None)
    total_works = biorxiv_works.get("meta").get("count")
    pages = math.ceil(total_works / open_alex.per_page)
    hub_ids = set()
    print(pages)

    for i in range(1, pages + 1):
        print(f"{i} / {pages + 1}")
        next_cursor = biorxiv_works.get("meta", {}).get("next_cursor", "*")
        for result in biorxiv_works.get("results", []):
            with transaction.atomic():
                doi = result.get("doi")
                if doi is None:
                    print(f"No Doi for result: {result}")
                    continue
                pure_doi = doi.split("doi.org/")[-1]

                primary_location = result.get("best_oa_location", None) or result.get(
                    "primary_location", {}
                )
                source = primary_location.get("source", {})
                oa = result.get("open_access", {})
                oa_pdf_url = oa.get("oa_url", None)
                url = primary_location.get("landing_page_url", None)
                title = normalize("NFKD", result.get("title", ""))
                raw_authors = result.get("authorships", [])
                concepts = result.get("concepts", [])
                abstract = rebuild_sentence_from_inverted_index(
                    result.get("abstract_inverted_index", {})
                )

                doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(pure_doi))
                url_paper_check = Paper.objects.filter(
                    Q(url_svf=SearchQuery(oa_pdf_url))
                    | Q(pdf_url_svf=SearchQuery(oa_pdf_url))
                )
                if doi_paper_check.exists() or url_paper_check.exists():
                    # This skips over the current iteration
                    print(f"Skipping paper with doi {pure_doi}")
                    continue

                data = {
                    "doi": pure_doi,
                    "url": url,
                    "raw_authors": format_raw_authors(raw_authors),
                    "title": title,
                    "paper_title": title,
                    "paper_publish_date": result.get("publication_date", None),
                    "is_open_access": oa.get("is_oa", None),
                    "oa_status": oa.get("oa_status", None),
                    "pdf_license": source.get("license", None),
                    "external_source": source.get("display_name", ""),
                    "abstract": abstract,
                    "open_alex_raw_json": result,
                }
                if oa_pdf_url and check_url_contains_pdf(oa_pdf_url):
                    data["pdf_url"] = oa_pdf_url

                paper = Paper(**data)
                paper.full_clean()
                paper.save()

                concept_names = [
                    concept.get("display_name", "other")
                    for concept in concepts
                    if concept.get("level", 0) == 0
                ]
                potential_hubs = []
                for concept_name in concept_names:
                    potential_hub = Hub.objects.filter(name__icontains=concept_name)
                    if potential_hub.exists():
                        potential_hub = potential_hub.first()
                        potential_hubs.append(potential_hub)
                        hub_ids.add(potential_hub.id)
                paper.hubs.add(*potential_hubs)

                download_pdf.apply_async((paper.id,), priority=4, countdown=4)
                if "biorxiv" in paper.url:
                    set_biorxiv_tweet_count.apply_async(
                        (
                            paper.url,
                            paper.doi,
                            paper.id,
                        ),
                        priority=4,
                        countdown=2,
                    )
        biorxiv_works = open_alex.get_data_from_source(
            biorxiv_id, None, cursor=next_cursor
        )
    reset_unified_document_cache(
        hub_ids=hub_ids,
        document_type=["paper"],
        filters=[NEW],
    )
    return total_works


@periodic_task(
    run_every=crontab(minute=45, hour=17), priority=3, queue=QUEUE_PULL_PAPERS
)
def pull_arxiv_papers_directly():
    if not PRODUCTION:
        return

    from paper.models import Paper

    categories = [
        "astro-ph",
        "cond-mat",
        "cs",
        "econ",
        "eess",
        "gr-qc",
        "hep-ex",
        "hep-lat",
        "hep-ph",
        "hep-th",
        "math",
        "math-ph",
        "nlin",
        "nucl-ex",
        "nucl-th",
        "physics",
        "q-bio",
        "q-fin",
        "quant-ph",
        "stat",
    ]
    total_works = 0
    hub_ids = set()

    for category in categories:
        url = "https://export.arxiv.org/rss/{}".format(category)
        feed = feedparser.parse(url)
        entries = []
        for entry in feed["entries"]:
            total_works += 1
            entry_id = entry["id"].split("http://arxiv.org/abs/")[1]
            entries.append(entry_id)

        search = arxiv.Search(id_list=entries)
        for i, result in enumerate(search.results()):
            entry_id = result.entry_id.split("http://arxiv.org/abs/")[1]
            pure_doi = "arXiv.{}".format(entry_id.split("v")[0])
            pdf_url = f"https://arxiv.org/pdf/{entry_id}.pdf"

            doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(pure_doi))
            url_paper_check = Paper.objects.filter(
                Q(url_svf=SearchQuery(url)) | Q(pdf_url_svf=SearchQuery(pdf_url))
            )
            if doi_paper_check.exists() or url_paper_check.exists():
                continue

            title = result.title
            abstract = result.summary
            publication_date = None
            raw_authors = []
            hubs = []
            publication_date = result.published
            for arxiv_cat in result.categories:
                cur_cat = get_category_name(arxiv_cat)
                hubs.append(cur_cat)

            try:
                raw_authors = [
                    {
                        "first_name": " ".join(author_name[:-1]),
                        "last_name": "".join(author_name[-1]),
                    }
                    for author in result.authors
                    if (author_name := author.name.split(" "))
                ]
            except Exception as e:
                print(e)
                sentry.log_error(e)

            data = {
                "doi": pure_doi,
                "url": result.entry_id,
                "raw_authors": format_raw_authors(raw_authors),
                "title": title,
                "paper_title": title,
                "paper_publish_date": publication_date,
                "is_open_access": True,
                "oa_status": "",
                "external_source": "arXiv",
                "abstract": abstract,
                "pdf_url": pdf_url,
            }

            try:
                paper = Paper(**data)
                paper.full_clean()
                paper.save()
                potential_hubs = []
                for concept_name in hubs:
                    potential_hub = Hub.objects.filter(name__icontains=concept_name)
                    if potential_hub.exists():
                        potential_hub = potential_hub.first()
                        potential_hubs.append(potential_hub)
                        hub_ids.add(potential_hub.id)
                paper.hubs.add(*potential_hubs)
                download_pdf.apply_async((paper.id,), priority=4, countdown=4)
            except Exception as e:
                sentry.log_error(e)
    reset_unified_document_cache(
        hub_ids=hub_ids,
        document_type=["paper"],
        filters=[NEW],
    )

    return total_works


@periodic_task(
    run_every=crontab(minute=0, hour="2"), priority=3, queue=QUEUE_PULL_PAPERS
)
def get_biorxiv_tweets():
    from paper.models import Paper

    three_days_ago = datetime.now() - timedelta(days=3)
    biorxiv_papers = Paper.objects.filter(
        external_source__icontains="bioRxiv", created_date__gte=three_days_ago
    )
    for paper in biorxiv_papers.iterator():
        set_biorxiv_tweet_count.apply_async(
            (
                paper.url,
                paper.doi,
                paper.id,
            ),
            priority=4,
            countdown=2,
        )


@periodic_task(
    run_every=crontab(minute=0, hour="*/3"), priority=3, queue=QUEUE_PULL_PAPERS
)
def pull_biorxiv(page=0, retry=0):
    if not PRODUCTION:
        return

    sentry.log_info("Starting Biorxiv pull")

    if retry > 2:
        return False

    try:
        res = requests.get(
            f"https://www.biorxiv.org/content/early/recent?page={page}", timeout=10
        )
        has_entries = _extract_biorxiv_entries(res.content)

        if has_entries:
            pull_biorxiv.apply_async(
                (page + 1, 0),
                priority=1,
                countdown=10,
            )
    except requests.ConnectionError:
        pull_biorxiv.apply_async(
            (page, retry + 1), priority=4, countdown=10 + (retry * 2)
        )
    except Exception as e:
        sentry.log_error(e)


@app.task(queue=QUEUE_PULL_PAPERS)
def set_biorxiv_tweet_count(url, doi, paper_id):
    from paper.models import Paper
    from researchhub_document.signals import sync_scores

    counts = _get_biorxiv_tweet_counts(url, doi)
    paper = Paper.objects.get(id=paper_id)
    paper.twitter_score = counts
    paper.save(update_fields=["twitter_score"])
    sync_scores(paper.unified_document, paper)


def _get_biorxiv_tweet_counts(url, doi):
    try:
        res = requests.get(
            f"https://connect.biorxiv.org/eval_get1.php?url={url}&doi={doi}", timeout=10
        )
        # For some reason, the request data comes back with "\ufeff" and then also has an open paren ( and a closed paren )
        escaped_json_res = json.loads(res.text.strip("\ufeff(").rstrip(res.text[-1]))
        count = 0
        for message in escaped_json_res["messages"]:
            count += message["count_tweets"] + message["count_retweets"]
        return count
    except Exception as e:
        print(e)
        sentry.log_error(e)
        return 0


def _extract_biorxiv_entries(html_content):
    from paper.models import Paper

    soup = BeautifulSoup(html_content, "lxml")
    today = datetime.now(tz=pytz_tz("US/Pacific"))
    today_string = today.strftime("%B-%d-%Y").lower()

    page = soup.find(id=today_string)
    if page:
        current_content = page.find_all(class_="highwire-cite-linked-title")
        for content in current_content:
            article_href = content.attrs.get("href")
            article_url = f"https://biorxiv.org{article_href}"
            article_url_check = Paper.objects.filter(doi_svf=SearchQuery(article_url))
            if article_url_check.exists():
                continue
            _extract_biorxiv_entry.apply_async((article_url,), priority=4, countdown=2)
        return True

    return False


@app.task(queue=QUEUE_PULL_PAPERS)
def _extract_biorxiv_entry(url, retry=0):
    from paper.models import Paper

    if retry > 2:
        return False

    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.content, "lxml")

        has_license_type_none = soup.find(class_="license-type-none")
        if has_license_type_none:
            # No reuse allowed without permission.
            return

        pure_doi = soup.find("meta", attrs={"name": "citation_doi"}).attrs.get(
            "content"
        )
        pdf_url = soup.find("meta", attrs={"name": "citation_pdf_url"}).attrs.get(
            "content"
        )

        doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(pure_doi))
        url_paper_check = Paper.objects.filter(
            Q(url_svf=SearchQuery(url)) | Q(pdf_url_svf=SearchQuery(pdf_url))
        )
        if doi_paper_check.exists() or url_paper_check.exists():
            return

        title = soup.find("meta", property="og:title").attrs.get("content")
        authors_html = soup.find_all("meta", attrs={"name": "citation_author"})
        raw_authors = [
            {
                "first_name": " ".join(author_name[:-1]),
                "last_name": "".join(author_name[-1]),
            }
            for raw_author in authors_html
            if (author_name := raw_author.attrs.get("content").split(" "))
        ]
        raw_publication_date = soup.find(
            "meta", attrs={"name": "citation_publication_date"}
        ).attrs.get("content")
        publication_date = datetime.strptime(raw_publication_date, "%Y/%d/%m").strftime(
            "%Y-%m-%d"
        )
        abstract = BeautifulSoup(
            soup.find("meta", attrs={"name": "citation_abstract"}).attrs.get("content"),
            "lxml",
        ).text
        journal = soup.find("meta", attrs={"name": "citation_journal_title"}).attrs.get(
            "content"
        )
        publisher = soup.find("meta", attrs={"name": "citation_publisher"}).attrs.get(
            "content"
        )

        license_block = soup.find(class_="license-type")
        if license_ref := license_block.findChild():
            license_url = license_ref.attrs.get("href")
            pdf_license = get_license_by_url(license_url)
        else:
            pdf_license = None

        external_source = f"{journal} ({publisher})"
        subject_area = soup.find(class_="highwire-article-collection-term")

        if subject_area:
            hub = subject_area.text.strip().lower()

        data = {
            "doi": pure_doi,
            "url": url,
            "raw_authors": raw_authors,
            "title": title,
            "paper_title": title,
            "paper_publish_date": publication_date,
            "pdf_license": pdf_license,
            "external_source": external_source,
            "abstract": abstract,
            "pdf_url": pdf_url,
            "twitter_score": _get_biorxiv_tweet_counts(url, pure_doi),
            "twitter_score_updated_date": datetime.now(),
        }
        paper = Paper(**data)
        paper.full_clean()
        paper.save()
        download_pdf.apply_async((paper.id,), priority=4, countdown=4)

        hub_ids = []
        if PRODUCTION:
            # Hard coded to add biorxiv preprints to specific biorxiv hub
            hub_ids = [436]
        if subject_area:
            potential_hub = Hub.objects.filter(name__icontains=hub)
            if potential_hub.exists():
                potential_hub = potential_hub.first()
                hub_ids.append(potential_hub.id)
        paper.hubs.add(*hub_ids)
        paper.unified_document.hubs.add(*hub_ids)

        reset_unified_document_cache(
            hub_ids=hub_ids,
            document_type=["paper"],
            filters=[NEW],
        )
    except requests.ConnectionError as e:
        sentry.log_error(e)
        _extract_biorxiv_entry.apply_async(
            (url, retry + 1), priority=6, countdown=2 * (retry + 1)
        )
    except Exception as e:
        sentry.log_error(e)
        return False
