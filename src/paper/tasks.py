from psycopg2.errors import UniqueViolation

import fitz
import logging
import os
import re
import requests
import shutil
import twitter
import urllib.request
import feedparser
import time

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
from purchase.models import Wallet
from researchhub.celery import app
from researchhub.settings import (
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
from utils import sentry
from utils.http import check_url_contains_pdf


@app.task
def censored_paper_cleanup(paper_id):
    Paper = apps.get_model('paper.Paper')
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
            logging.info('Did not find paper identifier to give to OR+cat:CID API')

    paper.authors.add(*orcid_authors)
    for author in paper.authors.iterator():
        Wallet.objects.get_or_create(author=author)
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

        if not paper.doi:
            doi = best_matching_result.get('DOI', paper.doi)
            paper.doi = doi

        url = best_matching_result.get('URL', None)
        publish_date = best_matching_result['created']['date-time']
        publish_date = datetime.strptime(publish_date, date_format).date()
        tagline = best_matching_result.get('abstract', '')
        tagline = re.sub(r'<[^<]+>', '', tagline)  # Removing any jat xml tags

        paper.url = url
        paper.paper_publish_date = publish_date

        if not paper.tagline:
            paper.tagline = tagline

        paper_cache_key = get_cache_key(None, 'paper', pk=paper_id)
        cache.delete(paper_cache_key)

        paper.check_doi()
        paper.save()
    except (UniqueViolation, IntegrityError) as e:
        sentry.log_info(e)
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
def handle_duplicate_doi(new_paper, doi):
    Paper = apps.get_model('paper.Paper')
    original_paper = Paper.objects.filter(doi=doi).order_by('uploaded_date')[0]
    merge_paper_votes(original_paper, new_paper)
    merge_paper_threads(original_paper, new_paper)
    merge_paper_bulletpoints(original_paper, new_paper)
    new_paper.delete()


# @periodic_task(
#     run_every=crontab(minute='*/30'),
#     priority=2,
#     options={'queue': APP_ENV}
# )
# TODO: Remove this completely?
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
                    {},
                    {},
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
    synchronous=False,
    meta=None,
):
    from paper.serializers import HubPaperSerializer
    from paper.views import PaperViewSet
    paper_view = PaperViewSet()
    http_req = HttpRequest()
    if meta:
        http_req.META = meta
    else:
        http_req.META = {'SERVER_NAME': 'localhost', 'SERVER_POR+cat:T': 80}
    paper_view.request = Request(http_req)
    papers = paper_view._get_filtered_papers(hub_id)
    order_papers = paper_view.calculate_paper_ordering(
        papers,
        ordering,
        start_date,
        end_date
    )

    context = {}
    context['user_no_balance'] = True

    page = paper_view.paginate_queryset(order_papers)
    serializer = HubPaperSerializer(page, many=True, context=context)
    serializer_data = serializer.data
    paginated_response = paper_view.get_paginated_response(
        {'data': serializer_data, 'no_results': False}
    )

    if synchronous:
        time_difference = end_date - start_date
    else:
        now = datetime.now()
        time_difference = now - now
    cache_pk = ''
    if time_difference.days > 365:
        cache_pk = f'{hub_id}_{ordering}_all_time'
    elif time_difference.days == 365:
        cache_pk = f'{hub_id}_{ordering}_year'
    elif time_difference.days == 30 or time_difference.days == 31:
        cache_pk = f'{hub_id}_{ordering}_month'
    elif time_difference.days == 7:
        cache_pk = f'{hub_id}_{ordering}_week'
    else:
        cache_pk = f'{hub_id}_{ordering}_today'

    cache_key_hub = get_cache_key(None, 'hub', pk=cache_pk)
    if cache_key_hub:
        cache.set(
            cache_key_hub,
            paginated_response.data,
            timeout=60*40
        )

    return paginated_response.data


# ARXIV Download Constants
RESULTS_PER_ITERATION = 50 # default is 10, if this goes too high like >=100 it seems to fail too often
WAIT_TIME = 3 # The docs recommend 3 seconds between queries
RETRY_WAIT = 8
RETRY_MAX = 20 # It fails a lot so retry a bunch
BASE_URL = 'http://export.arxiv.org/api/query?'

# Pull Daily (arxiv updates 20:00 EST)
@periodic_task(run_every=crontab(minute='45', hour='1'), priority=8)
def pull_papers(start=0):

    Paper = apps.get_model('paper.Paper')
    Summary = apps.get_model('summary.Summary')

    # Namespaces don't quite work with the feedparser, so hack them in
    feedparser.namespaces._base.Namespace.supported_namespaces['http://a9.com/-/spec/opensearch/1.1/'] = 'opensearch'
    feedparser.namespaces._base.Namespace.supported_namespaces['http://arxiv.org/schemas/atom'] = 'arxiv'

    # Code Inspired from https://static.arxiv.org/static/arxiv.marxdown/0.1/help/api/examples/python_arXiv_parsing_example.txt
    # Original Author: Julius B. Lucks

    # All categories
    search_query = "cat:astro-ph+OR+cat:astro-ph.CO+OR+cat:astro-ph.EP+OR+cat:astro-ph.GA+OR+cat:astro-ph.HE+OR+cat:astro-ph.IM+OR+cat:astro-ph.SR+OR+cat:cond-mat.dis-nn+OR+cat:cond-mat.mes-hall+OR+cat:cond-mat.mtrl-sci+OR+cat:cond-mat.other+OR+cat:cond-mat.quant-gas+OR+cat:cond-mat.soft+OR+cat:cond-mat.stat-mech+OR+cat:cond-mat.str-el+OR+cat:cond-mat.supr-con+OR+cat:cs.AI+OR+cat:cs.AR+OR+cat:cs.CC+OR+cat:cs.CE+OR+cat:cs.CG+OR+cat:cs.CL+OR+cat:cs.CR+OR+cat:cs.CV+OR+cat:cs.CY+OR+cat:cs.DB+OR+cat:cs.DC+OR+cat:cs.DL+OR+cat:cs.DM+OR+cat:cs.DS+OR+cat:cs.ET+OR+cat:cs.FL+OR+cat:cs.GL+OR+cat:cs.GR+OR+cat:cs.GT+OR+cat:cs.HC+OR+cat:cs.IR+OR+cat:cs.IT+OR+cat:cs.LG+OR+cat:cs.LO+OR+cat:cs.MA+OR+cat:cs.MM+OR+cat:cs.MS+OR+cat:cs.NA+OR+cat:cs.NE+OR+cat:cs.NI+OR+cat:cs.OH+OR+cat:cs.OS+OR+cat:cs.PF+OR+cat:cs.PL+OR+cat:cs.RO+OR+cat:cs.SC+OR+cat:cs.SD+OR+cat:cs.SE+OR+cat:cs.SI+OR+cat:cs.SY+OR+cat:econ.EM+OR+cat:eess.AS+OR+cat:eess.IV+OR+cat:eess.SP+OR+cat:gr-qc+OR+cat:hep-ex+OR+cat:hep-lat+OR+cat:hep-ph+OR+cat:hep-th+OR+cat:math.AC+OR+cat:math.AG+OR+cat:math.AP+OR+cat:math.AT+OR+cat:math.CA+OR+cat:math.CO+OR+cat:math.CT+OR+cat:math.CV+OR+cat:math.DG+OR+cat:math.DS+OR+cat:math.FA+OR+cat:math.GM+OR+cat:math.GN+OR+cat:math.GR+OR+cat:math.GT+OR+cat:math.HO+OR+cat:math.IT+OR+cat:math.KT+OR+cat:math.LO+OR+cat:math.MG+OR+cat:math.MP+OR+cat:math.NA+OR+cat:math.NT+OR+cat:math.OA+OR+cat:math.OC+OR+cat:math.PR+OR+cat:math.QA+OR+cat:math.RA+OR+cat:math.RT+OR+cat:math.SG+OR+cat:math.SP+OR+cat:math.ST+OR+cat:math-ph+OR+cat:nlin.AO+OR+cat:nlin.CD+OR+cat:nlin.CG+OR+cat:nlin.PS+OR+cat:nlin.SI+OR+cat:nucl-ex+OR+cat:nucl-th+OR+cat:physics.acc-ph+OR+cat:physics.ao-ph+OR+cat:physics.app-ph+OR+cat:physics.atm-clus+OR+cat:physics.atom-ph+OR+cat:physics.bio-ph+OR+cat:physics.chem-ph+OR+cat:physics.class-ph+OR+cat:physics.comp-ph+OR+cat:physics.data-an+OR+cat:physics.ed-ph+OR+cat:physics.flu-dyn+OR+cat:physics.gen-ph+OR+cat:physics.geo-ph+OR+cat:physics.hist-ph+OR+cat:physics.ins-det+OR+cat:physics.med-ph+OR+cat:physics.optics+OR+cat:physics.plasm-ph+OR+cat:physics.pop-ph+OR+cat:physics.soc-ph+OR+cat:physics.space-ph+OR+cat:q-bio.BM+OR+cat:q-bio.CB+OR+cat:q-bio.GN+OR+cat:q-bio.MN+OR+cat:q-bio.NC+OR+cat:q-bio.OT+OR+cat:q-bio.PE+OR+cat:q-bio.QM+OR+cat:q-bio.SC+OR+cat:q-bio.TO+OR+cat:q-fin.CP+OR+cat:q-fin.EC+OR+cat:q-fin.GN+OR+cat:q-fin.MF+OR+cat:q-fin.PM+OR+cat:q-fin.PR+OR+cat:q-fin.RM+OR+cat:q-fin.ST+OR+cat:q-fin.TR+OR+cat:quant-ph+OR+cat:stat.AP+OR+cat:stat.CO+OR+cat:stat.ME+OR+cat:stat.ML+OR+cat:stat.OT+OR+cat:stat.TH"
    sortBy = "submittedDate"
    sortOrder = "descending"

    i = start
    num_retries = 0
    while True:
        print("Entries: %i - %i" % (i, i+RESULTS_PER_ITERATION))

        query = 'search_query=%s&start=%i&max_results=%i&sortBy=%s&sortOrder=%s&' % (
                search_query,
                i,
                RESULTS_PER_ITERATION,
                sortBy,
                sortOrder)

        with urllib.request.urlopen(BASE_URL+query) as url:
            # If failed to fetch and we're not at the end retry until the limit
            if url.getcode() != 200:
                if num_retries < RETRY_MAX and i < int(feed.feed.opensearch_totalresults):
                    num_retries += 1
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    return

            response = url.read()
            feed = feedparser.parse(response)

            if i == start:
                print("total results", feed.feed.opensearch_totalresults)
                print("last updated", feed.feed.updated)

            # If no results and we're at the end or we've hit the retry limit give up
            if len(feed.entries) == 0:
                if num_retries < RETRY_MAX and i < int(feed.feed.opensearch_totalresults):
                    num_retries += 1
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    return

            # Run through each entry, and print out information
            for entry in feed.entries:
                num_retries = 0
                paper, created = Paper.objects.get_or_create(url=entry.id)

                if created:
                    paper.alternate_ids = {'arxiv': entry.id.split('/abs/')[-1]}

                    paper.title = entry.title
                    paper.abstract = entry.summary
                    paper.paper_publish_date = entry.published.split('T')[0]
                    paper.raw_authors = {'main_author': entry.author}

                    try:
                        paper.raw_authors['main_author'] += ' (%s)' % entry.arxiv_affiliation
                    except AttributeError:
                        pass

                    try:
                        paper.raw_authors['other_authors'] = [author.name for author in entry.authors]
                    except AttributeError:
                        pass

                    for link in entry.links:
                        try:
                            if link.title == 'pdf':
                                paper.pdf_url = link.href
                            if link.title == 'doi':
                                paper.doi = link.href.split('doi.org/')[-1]
                        except AttributeError:
                            pass

                    paper.save()

                    # If not published in the past week we're done
                    if Paper.objects.get(pk=paper.id).paper_publish_date < datetime.now().date() - timedelta(days=7):
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

        # Rate limit
        time.sleep(WAIT_TIME)

        i += RESULTS_PER_ITERATION

