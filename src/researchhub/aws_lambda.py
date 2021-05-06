import django
django.setup()

from paper.tasks import celery_extract_pdf_sections


def handler(event, context):
    cermine = event.get('cermine', False)
    if cermine:
        paper_id = cermine['paper_id']
        return celery_extract_pdf_sections(paper_id)
    return event
