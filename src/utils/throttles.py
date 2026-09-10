from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import UserRateThrottle

from oauth.models import Throttle
from researchhub.settings import EMAIL_WHITELIST

THROTTLE_RATES = {
    "user.burst": "7/min",
    "user.sustained": "60/day",
    "force_refresh": "5/min",
}


class UserCaptchaThrottle(UserRateThrottle):
    def get_user_ident(self, user):
        return user.pk

    def fmt_cache_key(self, ident):
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = self.get_user_ident(request.user)
        else:
            ident = self.get_ident(request)
        return self.fmt_cache_key(ident)

    def get_rate(self):
        return THROTTLE_RATES[self.scope]

    def allow_request(self, request, view):
        if (
            (self.rate is None)
            or (request.method in SAFE_METHODS)
            or (request.user.is_authenticated and (request.user.email is not None))
            or (request.user.is_authenticated and request.user.moderator)
            or (request.user.email in EMAIL_WHITELIST)
        ):
            return True

        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        self.history = self.cache.get(self.key, [])
        self.locked = self.cache.get(self.key + "_locked", False)
        self.now = self.timer()

        if self.locked:
            return self.throttle_failure()

        # Drop any requests from the history which have now passed the throttle duration
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        if len(self.history) >= self.num_requests:
            if not self.locked:
                self.lock(request.user, self.get_ident(request), self.key)
            return self.throttle_failure()
        else:
            return self.throttle_success()

    # Log to db and cache
    def lock(self, user, ident, key=None):
        if key is None:
            if user.is_authenticated:
                key = self.fmt_cache_key(self.get_user_ident(user))
            else:
                key = self.fmt_cache_key(ident)

        self.cache.set(key + "_locked", True, None)
        throt, _ = Throttle.objects.get_or_create(throttle_key=key)
        throt.locked = True
        throt.ident = ident
        if user.is_authenticated:
            throt.user = user
        throt.save()

    def throttle_success(self):
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)
        return True

    def throttle_failure(self):
        return False

    # To not reveal cool down time in details
    def wait(self):
        return None


class UserBurstRateThrottle(UserCaptchaThrottle):
    scope = "user.burst"


class UserSustainedRateThrottle(UserCaptchaThrottle):
    scope = "user.sustained"


class FeedRecommendationRefreshThrottle(UserRateThrottle):
    scope = "force_refresh"
    rate = "5/min"

    def allow_request(self, request, view):
        # Only throttle if the force refresh header is present and set to "true"
        force_refresh = request.META.get("HTTP_RH_FORCE_REFRESH", "").lower() == "true"
        if not force_refresh:
            return True
        return super().allow_request(request, view)
