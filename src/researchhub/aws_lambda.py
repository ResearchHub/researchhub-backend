import time

CERMINE_EXTRACT = 'cermine_extract'


def handler(event, context):
    if CERMINE_EXTRACT in event:
        data = event.get(CERMINE_EXTRACT)
        return app_handler(CERMINE_EXTRACT, data)
    return event


def app_handler(name, data):
    import django
    django.setup()

    from paper.utils import lambda_extract_pdf_sections

    retry = data.get('retry', 3)
    args = data.get('args')
    if retry >= 3:
        return

    if name == CERMINE_EXTRACT:
        from paper.tasks import celery_extract_pdf_sections
        res = celery_extract_pdf_sections(args)
        success = res[0]
        if not success:
            lambda_extract_pdf_sections(args, retry=retry+1)
    return
