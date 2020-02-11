import logging
import time

from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.utils import timezone
from django.core.files.base import ContentFile
from datetime import timedelta

from researchhub.celery import app
from paper.models import Paper

from utils.http import (
    http_request,
    RequestMethods as methods
)

def check_url_contains_pdf(url):
    try:
        r = http_request(methods.HEAD, url, timeout=3)
        content_type = r.headers.get('content-type')
    except Exception as e:
        raise ValidationError(f'Request to {url} failed: {e}')

    if 'application/pdf' not in content_type:
        raise ValueError(
            f'Did not find content type application/pdf at {url}'
        )
    else:
        return True

def get_pdf_from_url(url):
    response = http_request(methods.GET, url, timeout=3)
    pdf = ContentFile(response.content)
    return pdf

@app.task
def download_pdf(paper_id):
    print(paper_id)
    paper = Paper.objects.get(id=paper_id)

    if paper.url and check_url_contains_pdf(paper.url):
        pdf = get_pdf_from_url(paper.url)
        filename = paper.url.split('/').pop()
        paper.file.save(filename, pdf)

