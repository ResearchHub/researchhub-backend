CERMINE_EXTRACT = 'cermine_extract'


def handler(event, context):
    if CERMINE_EXTRACT in event:
        args = event.get(CERMINE_EXTRACT)
        return app_handler(CERMINE_EXTRACT, args)
    return event


def app_handler(name, args):
    import django
    django.setup()

    if name == CERMINE_EXTRACT:
        from paper.tasks import celery_extract_pdf_sections
        return celery_extract_pdf_sections(args)
    return
