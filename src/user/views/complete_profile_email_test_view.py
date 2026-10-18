from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from mailing_list.services import EmailService
from user.models import User

TEST_RECIPIENT = "canova@researchhub.foundation"


# TEMPORARY: remove once the complete-profile email has been verified.
@api_view(http_method_names=["GET"])
@permission_classes([AllowAny])
def send_complete_profile_test_email(request) -> Response:
    """Send the complete-profile email to the fixed test recipient."""
    user = get_object_or_404(
        User.objects.select_related("author_profile"), email=TEST_RECIPIENT
    )
    EmailService().send_email(
        TEST_RECIPIENT,
        "Finish your ResearchHub profile",
        {
            "profile_url": f"{settings.BASE_FRONTEND_URL}/author/"
            f"{user.author_profile.id}?edit_profile=true"
        },
        template="complete_profile_email",
    )
    return Response({"sent_to": TEST_RECIPIENT})
