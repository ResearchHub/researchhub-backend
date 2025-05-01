from allauth.account.models import EmailConfirmation, EmailConfirmationHMAC
from dj_rest_auth.registration.views import VerifyEmailView
from rest_framework.authtoken.models import Token
from rest_framework.response import Response


class CustomVerifyEmailView(VerifyEmailView):
    def post(self, request, *args, **kwargs):
        key = request.data.get("key")
        confirmation = EmailConfirmationHMAC.from_key(key)
        if not confirmation:
            # fallback to DB lookup (for older keys)
            confirmation = EmailConfirmation.objects.filter(key=key.lower()).first()
        if confirmation:
            confirmation.confirm(request)
            user = confirmation.email_address.user
            token, _ = Token.objects.get_or_create(user=user)
            return Response(
                {
                    "detail": "ok",
                    "key": token.key,
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                    },
                }
            )
        return Response({"detail": "Invalid key"}, status=400)
