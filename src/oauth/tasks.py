from oauth.services.user_signup_service import UserSignupService
from researchhub.celery import QUEUE_NOTIFICATION, app
from user.models import User


@app.task(queue=QUEUE_NOTIFICATION)
def send_welcome_email(user_id: int) -> None:
    """Send the welcome email to a newly registered user."""
    UserSignupService().send_welcome_email(User.objects.get(id=user_id))
