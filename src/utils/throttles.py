from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from oauth.models import Throttle

THROTTLE_RATES = {
    'user.burst': '7/min',
    'user.sustained': '60/day',
}

class UserCaptchaThrottle(UserRateThrottle):

    # For some reason it raise imporperly configured without this
    def get_rate(self):
        return THROTTLE_RATES[self.scope]

    def allow_request(self, request, view):
        # allow GET always
        if self.rate is None or request.method == 'GET':
            return True

        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        self.history = self.cache.get(self.key, [])
        self.locked = self.cache.get(self.key + '_locked', False)
        self.now = self.timer()

        if self.locked:
            return self.throttle_failure()

        # Drop any requests from the history which have now passed the throttle duration
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        if len(self.history) >= self.num_requests:
            # Log to db
            if not self.locked:
                throt, created = Throttle.objects.get_or_create(throttle_key=self.key)
                throt.locked = True
                throt.ident = self.get_ident(request)
                if request.user.is_authenticated:
                    throt.user = request.user
                throt.save()
            return self.throttle_failure()
        else:
            return self.throttle_success()

    def throttle_success(self):
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)
        return True

    def throttle_failure(self):
        if not self.locked:
            self.cache.set(self.key + '_locked', True, None)
        return False

    def captcha_complete(self, request):
        key = self.get_cache_key(request, None)
        locked = self.cache.get(key + '_locked', False)
        if locked:
            self.cache.delete(key + '_locked')
            self.cache.delete(key)

            throt, created = Throttle.objects.get_or_create(throttle_key=key)
            # TODO sentry logic for new user same ip here?
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
    scope = 'user.burst'

class UserSustainedRateThrottle(UserCaptchaThrottle):
    scope = 'user.sustained'

def captcha_unlock(request):
    UserSustainedRateThrottle().captcha_complete(request)
    UserBurstRateThrottle().captcha_complete(request)

THROTTLE_CLASSES = [
    UserBurstRateThrottle,
    UserSustainedRateThrottle,
]

