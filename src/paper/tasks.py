from psycopg2.errors import UniqueViolation

import fitz
import os
import re
import requests
import shutil

from datetime import datetime
from subprocess import call
from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.apps import apps
from django.core.cache import cache
from django.core.files import File
from django.db import IntegrityError
from django.db.models.functions import Extract, Now
from rest_framework.pagination import PageNumberPagination
from django.db.models import (
    Count,
    Q,
    F,
    Avg,
    IntegerField
)

from researchhub.celery import app
# from paper.serializers import HubPaperSerializer
# from paper.views import PaperViewSet

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
from utils import sentry
from utils.http import check_url_contains_pdf


@app.task
def download_pdf(paper_id):
    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    if paper.url and check_url_contains_pdf(paper.url):
        pdf = get_pdf_from_url(paper.url)
        filename = paper.url.split('/').pop()
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
def handle_duplicate_doi(new_paper, doi):
    Paper = apps.get_model('paper.Paper')
    original_paper = Paper.objects.filter(doi=doi).order_by('uploaded_date')[0]
    merge_paper_votes(original_paper, new_paper)
    merge_paper_threads(original_paper, new_paper)
    merge_paper_bulletpoints(original_paper, new_paper)
    new_paper.delete()


@periodic_task(run_every=crontab(minute='*/10'), priority=2)
def celery_preload_hub_papers():
    kwargs = {
        'page_number': 1,
    }
    preload_hub_papers(**kwargs)


@app.task
def preload_hub_papers(
    page_number,
    start_date,
    end_date,
    ordering,
    hub_id
):
    Vote = apps.get_model('paper.Vote')
    paper_view = PaperViewSet()
    threads_count = Count('threads')
    papers = paper_view._get_filtered_papers(hub_id, threads_count)

    if 'hot_score' in ordering:
        # constant > (hours in month) ** gravity * (discussion_weight + 2)
        INT_DIVISION = 90000000
        # num votes a comment is worth
        DISCUSSION_WEIGHT = 2

        gravity = 2.5
        threads_c = Count('threads')
        comments_c = Count('threads__comments')
        replies_c = Count('threads__comments__replies')
        upvotes = Count('vote', filter=Q(vote__vote_type=Vote.UPVOTE,))
        downvotes = Count('vote', filter=Q(vote__vote_type=Vote.DOWNVOTE,))
        now_epoch = Extract(Now(), 'epoch')
        created_epoch = Avg(
            Extract('vote__created_date', 'epoch'),
            output_field=IntegerField())
        time_since_calc = (now_epoch - created_epoch) / 3600

        numerator = (
            (threads_c + comments_c + replies_c)
            * DISCUSSION_WEIGHT +
            (upvotes - downvotes)
        )
        inverse_divisor = (
            INT_DIVISION
            / ((time_since_calc + 1) ** gravity)
        )
        order_papers = papers.annotate(
            numerator=numerator,
            hot_score=numerator * inverse_divisor,
            divisor=inverse_divisor
        )
        if ordering[0] == '-':
            order_papers = order_papers.order_by(
                F('hot_score').desc(nulls_last=True),
                '-numerator'
            )
        else:
            order_papers = order_papers.order_by(
                F('hot_score').asc(nulls_last=True),
                'numerator'
            )

    elif 'score' in ordering:
        upvotes = Count(
            'vote',
            filter=Q(
                vote__vote_type=Vote.UPVOTE,
                vote__updated_date__gte=start_date,
                vote__updated_date__lte=end_date
            )
        )
        downvotes = Count(
            'vote',
            filter=Q(
                vote__vote_type=Vote.DOWNVOTE,
                vote__updated_date__gte=start_date,
                vote__updated_date__lte=end_date
            )
        )

        all_time_upvotes = Count(
            'vote',
            filter=Q(
                vote__vote_type=Vote.UPVOTE,
            )
        )
        all_time_downvotes = Count(
            'vote',
            filter=Q(
                vote__vote_type=Vote.DOWNVOTE,
            )
        )

        order_papers = papers.annotate(
            score_in_time=upvotes - downvotes,
            score_all_time=all_time_upvotes + all_time_downvotes,
        ).order_by(ordering + '_in_time', ordering + '_all_time')

    elif 'discussed' in ordering:
        threads_c = Count(
            'threads',
            filter=Q(
                threads__created_date__gte=start_date,
                threads__created_date__lte=end_date
            )
        )
        comments = Count(
            'threads__comments',
            filter=Q(
                threads__comments__created_date__gte=start_date,
                threads__comments__created_date__lte=end_date
            )
        )
        all_time_comments = Count(
            'threads__comments',
        )
        order_papers = papers.annotate(
            discussed=threads_c + comments,
            discussed_secondary=threads_count + all_time_comments
        ).order_by(ordering, ordering + '_secondary')

    else:
        order_papers = papers.order_by(ordering)

    page = paper_view.paginate_queryset(order_papers)
    context = paper_view.get_serializer_context()
    serializer = HubPaperSerializer(page, many=True, context=context)
    serializer_data = serializer.data
    if page_number == 1:
        cache.set(cache_key_hub, serializer_data, timeout=60*60*24*7)
        cache.set(cache_key_papers, order_papers[:15], timeout=60*60*24*7)
