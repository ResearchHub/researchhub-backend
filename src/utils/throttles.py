from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from oauth.models import Throttle
from researchhub.settings import EMAIL_WHITELIST

THROTTLE_RATES = {
    "user.burst": "7/min",
    "user.sustained": "60/day",
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
            or (
                request.user.is_authenticated
                and (request.user.email is not None)
                and request.user.email.endswith("@quantfive.org")
            )
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
        throt, created = Throttle.objects.get_or_create(throttle_key=key)
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

    def captcha_complete(self, request):
        """
        Unlocks user on throttle cache and db level
        """
        # unique id for requester
        key = self.get_cache_key(request, None)
        locked = self.cache.get(key + "_locked", False)
        if locked:
            self.cache.delete(key + "_locked")
            self.cache.delete(key)

            throt, created = Throttle.objects.get_or_create(throttle_key=key)
            # TODO Log to sentry when we see a new user with same ip?
            throt.locked = False
            throt.ident = self.get_ident(request)
            if request.user.is_authenticated:
                throt.user = request.user
            throt.captchas_completed = throt.captchas_completed + 1
            throt.save()
            return throt
        else:
            return True

    # To not reveal cool down time in details
    def wait(self):
        return None


class UserBurstRateThrottle(UserCaptchaThrottle):
    scope = "user.burst"


class UserSustainedRateThrottle(UserCaptchaThrottle):
    scope = "user.sustained"


def captcha_unlock(request):
    UserSustainedRateThrottle().captcha_complete(request)
    UserBurstRateThrottle().captcha_complete(request)


THROTTLE_CLASSES = [
    UserBurstRateThrottle,
    UserSustainedRateThrottle,
]
