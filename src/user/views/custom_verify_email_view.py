import logging

from allauth.account.models import EmailConfirmation, EmailConfirmationHMAC
from dj_rest_auth.registration.views import VerifyEmailView
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.response import Response

User = get_user_model()
logger = logging.getLogger(__name__)


# CustomVerifyEmailView enhances the default email verification endpoint.
# In addition to verifying the user's email, it returns an authentication token
# (so the user can be automatically logged in after verification) and basic user info.
# This is useful for SPA flows where you want to log the user in immediately
# after they click the verification link.
class CustomVerifyEmailView(VerifyEmailView):
    def post(self, request, *args, **kwargs):

        key = request.data.get("key")

        if not key:
            logger.warning("No key provided in request.")
            return Response({"detail": "No key provided"}, status=400)

        # Store user info BEFORE calling parent method
        # because the parent method will override it
        user_id = None

        confirmation = EmailConfirmationHMAC.from_key(key)

        if not confirmation:
            confirmation = EmailConfirmation.objects.filter(key=key.lower()).first()

        if confirmation:
            user = confirmation.email_address.user
            user_id = user.id

        # Call parent method to handle verification
        parent_response = super().post(request, *args, **kwargs)

        if parent_response.status_code != 200 or not user_id:
            return parent_response

        try:
            user = User.objects.get(id=user_id)
            token, _ = Token.objects.get_or_create(user=user)

            # Return the response with token
            return Response(
                {
                    "detail": "ok",
                    "key": token.key,
                    "user": {
                        "id": user_id,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Could not generate token response: {str(e)}")

        # Return parent response if:
        # - Parent verification failed, OR
        # - We don't have user info, OR
        # - We couldn't generate the token response
        return parent_response
