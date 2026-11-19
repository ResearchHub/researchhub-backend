from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from user.related_models.auth_token_activity_model import AuthTokenActivity

LAST_USED_WRITE_INTERVAL = timedelta(hours=1)


class AuthTokenService:
    def get_active_token(self, key: str) -> Token | None:
        token = Token.objects.select_related("user", "activity").filter(key=key).first()
        if token is None or not token.user.is_active or self.is_expired(token):
            return None
        return token

    def is_expired(self, token: Token, now: datetime | None = None) -> bool:
        now = now or timezone.now()
        issued_at, last_used_at = self._timestamps(token)
        return (
            now >= issued_at + settings.AUTH_TOKEN_ABSOLUTE_LIFETIME
            or now >= last_used_at + settings.AUTH_TOKEN_IDLE_LIFETIME
        )

    def record_use(self, token: Token, now: datetime | None = None) -> None:
        now = now or timezone.now()
        activity = getattr(token, "activity", None)
        if activity is None:
            AuthTokenActivity.objects.get_or_create(
                token=token,
                defaults={"issued_at": token.created, "last_used_at": now},
            )
        elif now - activity.last_used_at >= LAST_USED_WRITE_INTERVAL:
            AuthTokenActivity.objects.filter(pk=token.pk, last_used_at__lt=now).update(
                last_used_at=now
            )
            activity.last_used_at = now

    def issue(self, user) -> Token:
        now = timezone.now()
        token = Token.objects.select_related("activity").filter(user=user).first()
        if token is None or self._should_replace(token, now):
            return self.replace(user, now)
        self.record_use(token, now)
        return token

    @transaction.atomic
    def replace(self, user, now: datetime | None = None) -> Token:
        now = now or timezone.now()
        Token.objects.filter(user=user).delete()
        token, _ = Token.objects.get_or_create(user=user)
        AuthTokenActivity.objects.get_or_create(
            token=token, defaults={"issued_at": now, "last_used_at": now}
        )
        return token

    def revoke(self, user) -> None:
        Token.objects.filter(user=user).delete()

    def _should_replace(self, token: Token, now: datetime) -> bool:
        issued_at, _ = self._timestamps(token)
        remaining = issued_at + settings.AUTH_TOKEN_ABSOLUTE_LIFETIME - now
        return self.is_expired(token, now) or (
            remaining < settings.AUTH_TOKEN_IDLE_LIFETIME
        )

    def _timestamps(self, token: Token) -> tuple[datetime, datetime]:
        activity = getattr(token, "activity", None)
        if activity is None:
            return token.created, token.created
        return activity.issued_at, activity.last_used_at


def create_auth_token(token_model, user, serializer) -> Token:
    return AuthTokenService().issue(user)
