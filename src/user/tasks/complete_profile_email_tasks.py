from researchhub.celery import QUEUE_NOTIFICATION, app
from user.services.complete_profile_email_service import CompleteProfileEmailService


@app.task(queue=QUEUE_NOTIFICATION)
def send_complete_profile_email_task(user_id: int) -> None:
    """Send the complete-profile email to one user if they are eligible."""
    CompleteProfileEmailService().send_if_eligible(user_id)


@app.task(queue=QUEUE_NOTIFICATION)
def send_week_old_complete_profile_emails_task() -> None:
    """Send the complete-profile email to eligible week-old accounts."""
    CompleteProfileEmailService().send_to_week_old_accounts()
