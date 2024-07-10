from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.conf import settings

import hmac


class PersonaWebhookView(APIView):
    """
    View for processing Persona webhooks.

    This view handles incoming POST requests from Persona.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Process incoming webhook from Persona.
        """
        persona_signature = request.headers.get("Persona-Signature")

        if not persona_signature:
            return Response(
                {"message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED
            )

        if not self.validate_signature(request):
            return Response(
                {"message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED
            )

        # Currently a no-op
        # FIXME: Replace with implementation
        print(f"Webhook received: {request.body}")

        return Response(
            {"message": "Webhook successfully processed"}, status=status.HTTP_200_OK
        )

    def validate_signature(self, request: Request) -> bool:
        """
        Validate the signature of the incoming request.

        Also see: https://docs.withpersona.com/docs/webhooks-best-practices#checking-signatures
        """
        t, v1 = [
            value.split("=")[1]
            for value in request.headers["Persona-Signature"].split(",")
        ]

        computed_digest = hmac.new(
            settings.PERSONA_WEBHOOK_SECRET.encode(),
            (t + "." + request.body.decode("utf-8")).encode(),
            "sha256",
        ).hexdigest()

        return hmac.compare_digest(v1, computed_digest)
