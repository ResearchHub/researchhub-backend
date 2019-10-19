from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreateSummary(RuleBasedPermission):
    message = 'Not enough reputation to create summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 5


class UpdateSummary(RuleBasedPermission):
    message = 'Not enough reputation to update summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class FlagSummary(RuleBasedPermission):
    message = 'Not enough reputation to flag summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class ApproveSummary(RuleBasedPermission):
    message = 'Not enough reputation to approve summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class RejectSummary(RuleBasedPermission):
    message = 'Not enough reputation to reject summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50
