import hmac
import logging
from hashlib import sha1

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from user.related_models.user_model import User

logger = logging.getLogger(__name__)


class SiftWebhookView(APIView):
    """
    View for processing Sift webhooks.

    This view handles incoming POST requests from Sift.
    Authentication is handled by validating the signature from the incoming request.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request, *args, **kwargs) -> Response:
        postback_signature = request.headers.get("X-Sift-Science-Signature")

        if not postback_signature or not self._validate_signature(request):
            return Response({"message:": "Unauthorized"}, status=401)

        decision_id = request.data["decision"]["id"]
        user_id = request.data["entity"]["id"]

        user = User.objects.get(id=user_id)

        if (
            user.moderator
            or user.email in settings.EMAIL_WHITELIST
            or user.id in settings.SIFT_MODERATION_WHITELIST
        ):
            logger.info(f"Skipping moderation for whitelisted user id={user.id}")
        else:
            if "mark_as_probable_spammer_content_abuse" in decision_id:
                logger.info(f"Flagging user id={user.id} as possible spammer")
                user.set_probable_spammer()
            elif "suspend_user_content_abuse" in decision_id:
                logger.info(f"Suspending user id={user.id}")
                user.set_suspended(is_manual=False)
                user.is_active = False
                user.save(update_fields=["is_active"])

        return Response({"message:": "Webhook successfully processed"}, status=200)

    def _validate_signature(self, request: Request) -> bool:
        """
        Validate the incoming Sift signature.
        """
        postback_signature = request.headers.get("X-Sift-Science-Signature")

        if not postback_signature:
            return False

        key = settings.SIFT_WEBHOOK_SECRET_KEY.encode("utf-8")
        postback_body = request.body

        h = hmac.new(key, postback_body, sha1)
        verification_signature = "sha1={}".format(h.hexdigest())

        return verification_signature == postback_signature
