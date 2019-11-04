from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class ProposeSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to propose summary edit.'

    def satisfies_rule(self, request):
        if request.method == RequestMethods.POST:
            return request.user.reputation >= 1
        return True


class UpdateOrDeleteSummaryEdit(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        method = request.method
        user = request.user
        if (
            (method == RequestMethods.PUT)
            or (method == RequestMethods.PATCH)
            or (method == RequestMethods.DELETE)
        ):
            if (obj.approved_by is None) and (obj.paper.uploaded_by == user):
                return True
            elif obj.approved is True:
                return False
            return user == obj.proposed_by
        return True


class FlagSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to flag summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class ApproveSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to approve summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50


class RejectSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to reject summary.'

    def satisfies_rule(self, request):
        return request.user.reputation >= 50
