from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class CreateSummary(RuleBasedPermission):
    message = 'Not enough reputation to create summary.'

    def satisfies_rule(self, request):
        if request.method == 'POST':
            return request.user.reputation >= 5
        return True


class UpdateSummary(RuleBasedPermission):
    message = 'Not enough reputation to update summary.'

    def satisfies_rule(self, request):
        if (request.method == 'PUT') or (request.method == 'PATCH'):
            return request.user.reputation >= 50
        return True


class ProposeSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to propose summary edit.'

    def satisfies_rule(self, request):
        if request.method == 'POST':
            return request.user.reputation >= 5
        return True


# TODO: Implement
class UpdateSummaryEdit(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request):
        # Request user is summary edit proposer
        pass


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
