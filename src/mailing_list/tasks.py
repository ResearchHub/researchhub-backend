from mailing_list.services import EmailService
from researchhub.celery import QUEUE_NOTIFICATION, app


@app.task(queue=QUEUE_NOTIFICATION)
def send_message_email(
    recipients: list[str],
    subject: str,
    message: str,
    *,
    link: str | None = None,
    heading: str | None = None,
) -> None:
    """Send a prepared message to an email audience."""
    EmailService().send_message_email(
        recipients, subject, message, link=link, heading=heading
    )
