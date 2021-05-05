import django
django.setup()

from paper.aws_lambda import test
from paper.tasks import celery_extract_pdf_sections
from researchhub.settings import TEST_ENV


def handler(event, context):
    blah = event.get('cermine', False)
    if blah:
        return celery_extract_pdf_sections(blah)
    return TEST_ENV, event
