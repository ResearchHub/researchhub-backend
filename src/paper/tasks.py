import logging
import time

from celery.decorators import periodic_task
from celery.task.schedules import crontab

from django.utils import timezone
from datetime import timedelta

from researchhub.celery import app
from paper.models import Paper
from paper.utils import check_url_contains_pdf, get_pdf_from_url

@app.task
def download_pdf(paper_id):
    paper = Paper.objects.get(id=paper_id)

    if paper.url and check_url_contains_pdf(paper.url):
        pdf = get_pdf_from_url(paper.url)
        filename = paper.url.split('/').pop()
        paper.file.save(filename, pdf)
        paper.save(update_fields=['file'])

