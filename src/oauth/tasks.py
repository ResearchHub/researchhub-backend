from django.core.management import call_command

from researchhub.celery import app


@app.task
def clear_expired_tokens():
    """
    Deletes expired OAuth tokens and grants, then CIMD clients that no longer
    hold any, using django-oauth-toolkit's cleanup commands.
    """
    call_command("cleartokens")
    call_command("clearcimdapplications")
