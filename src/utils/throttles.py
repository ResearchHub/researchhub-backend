from rest_framework.throttling import UserRateThrottle, AnonRateThrottle

THROTTLE_RATES = {
    'user.burst': '7/min',
    'user.sustained': '60/day',
}

class UserNonGETThrottle(UserRateThrottle):

    # For some reason it raise imporperly configured without this
    def get_rate(self):
        return THROTTLE_RATES[self.scope]

    # allow GET and only rate limit on non GET requests
    def allow_request(self, request, view):
        if request.method != 'GET':
            sup = super(UserRateThrottle, self).allow_request(request, view)
            return sup
        else:
            return True

    # To not reveal cool down time in details
    def wait(self):
        return None

class UserBurstRateThrottle(UserNonGETThrottle):
    scope = 'user.burst'

class UserSustainedRateThrottle(UserNonGETThrottle):
    scope = 'user.sustained'

THROTTLE_CLASSES = [
    UserBurstRateThrottle,
    UserSustainedRateThrottle,
]
