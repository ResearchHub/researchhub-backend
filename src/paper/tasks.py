from psycopg2.errors import UniqueViolation

import fitz
import logging
import os
import re
import requests
import shutil
import twitter

from datetime import datetime, timedelta, timezone
from subprocess import call
from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.apps import apps
from django.core.cache import cache
from django.core.files import File
from django.db import IntegrityError
from django.http.request import HttpRequest
from rest_framework.request import Request
from discussion.models import Thread, Comment
from bullet_point.models import BulletPoint
from summary.models import Summary
from researchhub.celery import app
from researchhub.settings import (
    APP_ENV,
    TWITTER_CONSUMER_KEY,
    TWITTER_CONSUMER_SECRET,
    TWITER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
)
from paper.utils import (
    check_crossref_title,
    check_pdf_title,
    get_pdf_from_url,
    get_crossref_results,
    fitz_extract_figures,
    merge_paper_bulletpoints,
    merge_paper_threads,
    merge_paper_votes,
    get_cache_key,
)
from paper.scholarcy import ScholarcyMetadata
from utils import sentry
from utils.http import check_url_contains_pdf


@app.task
def download_pdf(paper_id):
    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    paper_url = paper.url
    pdf_url = paper.pdf_url
    url = pdf_url or paper_url
    url_has_pdf = (check_url_contains_pdf(paper_url) or pdf_url)

    if paper_url and url_has_pdf:
        pdf = get_pdf_from_url(url)
        filename = paper.url.split('/').pop()
        if not filename.endswith('.pdf'):
            filename += '.pdf'
        paper.file.save(filename, pdf)
        paper.save(update_fields=['file'])


@app.task
def add_references(paper_id):
    if paper_id is None:
        return

    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    paper.add_references()


@app.task
def add_orcid_authors(paper_id):
    if paper_id is None:
        return

    from utils.orcid import orcid_api

    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    orcid_authors = []
    while True:
        if paper.doi is not None:
            orcid_authors = orcid_api.get_authors(doi=paper.doi)
            break
        arxiv_id = paper.alternate_ids.get('arxiv', None)
        if arxiv_id is not None:
            orcid_authors = orcid_api.get_authors(arxiv=arxiv_id)
            break
        break

        if len(orcid_authors) < 1:
            print('No authors to add')
            logging.info('Did not find paper identifier to give to ORCID API')

    paper.authors.add(*orcid_authors)
    logging.info(f'Finished adding orcid authors to paper {paper.id}')


@app.task
def celery_extract_figures(paper_id):
    if paper_id is None:
        return

    Paper = apps.get_model('paper.Paper')
    Figure = apps.get_model('paper.Figure')
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        return

    path = f'/tmp/figures/{paper_id}/'
    filename = f'{paper.id}.pdf'
    file_path = f'{path}{filename}'
    file_url = file.url

    if not os.path.isdir(path):
        os.mkdir(path)

    try:
        res = requests.get(file_url)
        with open(file_path, 'wb+') as f:
            f.write(res.content)

        fitz_extract_figures(file_path)

        figures = os.listdir(path)
        if len(figures) == 1:  # Only the pdf exists
            args = [
                'java',
                '-jar',
                'pdffigures2-assembly-0.1.0.jar',
                file_path,
                '-m',
                path,
                '-d',
                path,
                '-e'
            ]
            call(args)
            figures = os.listdir(path)

        for extracted_figure in figures:
            extracted_figure_path = f'{path}{extracted_figure}'
            if '.png' in extracted_figure:
                with open(extracted_figure_path, 'rb') as f:
                    extracted_figures = Figure.objects.filter(paper=paper)
                    if not extracted_figures.filter(
                        file__contains=f.name,
                        figure_type=Figure.FIGURE
                    ):
                        Figure.objects.create(
                            file=File(f),
                            paper=paper,
                            figure_type=Figure.FIGURE
                        )
    except Exception as e:
        sentry.log_error(e)
    finally:
        shutil.rmtree(path)
        cache_key = get_cache_key(None, 'figure', pk=paper_id)
        cache.delete(cache_key)


@app.task
def celery_extract_pdf_preview(paper_id):
    if paper_id is None:
        return

    Paper = apps.get_model('paper.Paper')
    Figure = apps.get_model('paper.Figure')
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        return

    path = f'/tmp/figures/preview-{paper_id}/'
    filename = f'{paper.id}.pdf'
    file_path = f'{path}{filename}'
    file_url = file.url

    if not os.path.isdir(path):
        os.mkdir(path)

    try:
        res = requests.get(file_url)
        with open(file_path, 'wb+') as f:
            f.write(res.content)

        doc = fitz.open(file_path)
        extracted_figures = Figure.objects.filter(paper=paper)
        for page in doc:
            pix = page.getPixmap(alpha=False)
            output_filename = f'{file_path}-{page.number}.png'
            pix.writePNG(output_filename)

            if not extracted_figures.filter(
                file__contains=output_filename,
                figure_type=Figure.PREVIEW
            ):
                with open(output_filename, 'rb') as f:
                    Figure.objects.create(
                        file=File(f),
                        paper=paper,
                        figure_type=Figure.PREVIEW
                    )
    except Exception as e:
        sentry.log_error(e)
    finally:
        shutil.rmtree(path)
        cache_key = get_cache_key(None, 'figure', pk=paper_id)
        cache.delete(cache_key)


@app.task
def celery_extract_meta_data(paper_id, title, check_title):
    if paper_id is None:
        return

    Paper = apps.get_model('paper.Paper')
    date_format = '%Y-%m-%dT%H:%M:%SZ'
    paper = Paper.objects.get(id=paper_id)

    if check_title:
        has_title = check_pdf_title(title, paper.file)
        if not has_title:
            return

    best_matching_result = get_crossref_results(title, index=1)[0]

    try:
        if 'title' in best_matching_result:
            crossref_title = best_matching_result.get('title', [''])[0]
        else:
            crossref_title = best_matching_result.get('container-title', [''])
            crossref_title = crossref_title[0]

        similar_title = check_crossref_title(title, crossref_title)

        if not similar_title:
            return

        doi = best_matching_result.get('DOI', None)
        url = best_matching_result.get('URL', None)
        publish_date = best_matching_result['created']['date-time']
        publish_date = datetime.strptime(publish_date, date_format).date()
        tagline = best_matching_result.get('abstract', '')
        tagline = re.sub(r'<[^<]+>', '', tagline)  # Removing any jat xml tags

        paper.doi = doi
        paper.url = url
        paper.paper_publish_date = publish_date

        if not paper.tagline:
            paper.tagline = tagline

        paper_cache_key = get_cache_key(None, 'paper', pk=paper_id)
        cache.delete(paper_cache_key)
        paper.save()
    except (UniqueViolation, IntegrityError) as e:
        sentry.log_info(e)
        handle_duplicate_doi(paper, doi)
    except Exception as e:
        sentry.log_info(e)


@app.task
def celery_extract_twitter_comments(paper_id):
    if paper_id is None:
        return

    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    url = paper.url
    if not url:
        return

    source = 'twitter'
    try:
        api = twitter.Api(
            consumer_key=TWITTER_CONSUMER_KEY,
            consumer_secret=TWITTER_CONSUMER_SECRET,
            access_token_key=TWITER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
            tweet_mode='extended'
        )

        results = api.GetSearch(
            term=f'{url} -filter:retweets'
        )
        for res in results:
            source_id = res.id_str
            username = res.user.screen_name
            text = res.full_text
            thread_user_profile_img = res.user.profile_image_url_https
            thread_created_date = res.created_at_in_seconds
            thread_created_date = datetime.fromtimestamp(
                thread_created_date,
                timezone.utc
            )

            thread_exists = Thread.objects.filter(
                external_metadata__source_id=source_id
            ).exists()

            if not thread_exists:
                external_thread_metadata = {
                    'source_id': source_id,
                    'username': username,
                    'picture': thread_user_profile_img,
                    'url': f'https://twitter.com/{username}/status/{source_id}'
                }
                thread = Thread.objects.create(
                    paper=paper,
                    source=source,
                    external_metadata=external_thread_metadata,
                    plain_text=text,
                )
                thread.created_date = thread_created_date
                thread.save()

                replies = api.GetSearch(
                    term=f'to:{username}'
                )
                for reply in replies:
                    reply_username = reply.user.screen_name
                    reply_id = reply.id_str
                    reply_text = reply.full_text
                    comment_user_img = reply.user.profile_image_url_https
                    comment_created_date = reply.created_at_in_seconds
                    comment_created_date = datetime.fromtimestamp(
                        comment_created_date,
                        timezone.utc
                    )

                    reply_exists = Comment.objects.filter(
                        external_metadata__source_id=reply_id
                    ).exists()

                    if not reply_exists:
                        external_comment_metadata = {
                            'source_id': reply_id,
                            'username': reply_username,
                            'picture': comment_user_img,
                            'url': f'https://twitter.com/{reply_username}/status/{reply_id}'
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


@app.task
def celery_extract_scholarcy_data(paper_id, url, options):
    if paper_id is None:
        return

    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    scholarcy = ScholarcyMetadata(url)

    if options.get('get_key_takeaways', False):
        celery_extract_scholarcy_takeaways(paper, scholarcy)

    if options.get('get_summary', False):
        celery_extract_scholarcy_summary(paper, scholarcy)


@app.task
def celery_extract_scholarcy_takeaways(paper, scholarcy):
    takeaways = scholarcy.get_key_takeaways()
    for i, takeaway in enumerate(takeaways):
        BulletPoint.objects.create(
            paper=paper,
            created_by=None,
            plain_text=takeaway,
            ordinal=i+1,
            bullet_type=BulletPoint.BULLETPOINT_KEYTAKEAWAY
        )


@app.task
def celery_extract_scholarcy_summary(paper, scholarcy):
    summary = scholarcy.get_summary()
    summary_json = {'ops': [
        {
            'insert': summary
        }
    ]}
    summary_obj = Summary.objects.create(
        summary=summary_json,
        summary_plain_text=summary,
        paper=paper,
        approved=True,
    )
    paper.summary = summary_obj
    paper.save()

    cache_key = get_cache_key(None, 'paper', pk=paper.id)
    cache.delete(cache_key)


@app.task
def handle_duplicate_doi(new_paper, doi):
    Paper = apps.get_model('paper.Paper')
    original_paper = Paper.objects.filter(doi=doi).order_by('uploaded_date')[0]
    merge_paper_votes(original_paper, new_paper)
    merge_paper_threads(original_paper, new_paper)
    merge_paper_bulletpoints(original_paper, new_paper)
    new_paper.delete()


@periodic_task(
    run_every=crontab(minute='*/30'),
    priority=2,
    options={'queue': APP_ENV}
)
def celery_preload_hub_papers():
    # hub_ids = Hub.objects.values_list('id', flat=True)
    hub_ids = [0]
    orderings = (
        '-hot_score',
        '-score',
        '-discussed',
        '-uploaded_date',
    )
    filter_types = (
        'year',
        'month',
        'week',
        'today',
    )

    start_date_hour = 7
    end_date = today = datetime.now()
    for hub_id in hub_ids:
        for ordering in orderings:
            for filter_type in filter_types:
                cache_pk = f'{hub_id}_{ordering}_{filter_type}'
                if filter_type == 'year':
                    td = timedelta(days=365)
                elif filter_type == 'month':
                    td = timedelta(days=30)
                elif filter_type == 'week':
                    td = timedelta(days=7)
                else:
                    td = timedelta(days=0)

                cache_key = get_cache_key(None, 'hub', pk=cache_pk)
                datetime_diff = today - td
                year = datetime_diff.year
                month = datetime_diff.month
                day = datetime_diff.day
                start_date = datetime(
                    year,
                    month,
                    day,
                    hour=start_date_hour
                )

                args = (
                    1,
                    start_date,
                    end_date,
                    ordering,
                    hub_id,
                    cache_key
                )
                preload_hub_papers(*args)
                break
            break
        break


@app.task
def preload_hub_papers(
    page_number,
    start_date,
    end_date,
    ordering,
    hub_id,
    cache_key,
):
    from paper.serializers import HubPaperSerializer
    from paper.views import PaperViewSet
    paper_view = PaperViewSet()
    paper_view.request = Request(HttpRequest())
    papers = paper_view._get_filtered_papers(hub_id)
    order_papers = paper_view.calculate_paper_ordering(
        papers,
        ordering,
        start_date,
        end_date
    )

    page = paper_view.paginate_queryset(order_papers)
    serializer = HubPaperSerializer(page, many=True)
    serializer_data = serializer.data
    if cache_key:
        cache.set(
            cache_key,
            (serializer_data, order_papers[:15]),
            timeout=60*10
        )
    return (serializer_data, order_papers[:15])
