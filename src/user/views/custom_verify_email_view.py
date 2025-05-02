from allauth.account.models import EmailConfirmation, EmailConfirmationHMAC
from dj_rest_auth.registration.views import VerifyEmailView
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.response import Response

User = get_user_model()


class CustomVerifyEmailView(VerifyEmailView):
    def post(self, request, *args, **kwargs):

        key = request.data.get("key")

        if not key:
            return Response({"detail": "Invalid key"}, status=400)

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

        # If parent verification was successful AND we have user info
        if parent_response.status_code == 200 and user_id:

            try:
                user = User.objects.get(id=user_id)
                token, created = Token.objects.get_or_create(user=user)

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
                # Log the error but don't raise it - just continue to return parent response
                print(f"NOTE: Could not generate token response: {str(e)}")
                print("Falling back to parent response.")

        # Return parent response if:
        # - Parent verification failed, OR
        # - We don't have user info, OR
        # - We couldn't generate the token response
        return parent_response
