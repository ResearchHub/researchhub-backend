from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class ProposeSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to propose summary edit.'

    def satisfies_rule(self, request):
        if request.method == RequestMethods.POST:
            return request.user.reputation >= 1 and not request.user.probable_spammer and not request.user.is_suspended
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
            if (
                self.is_first_summary(obj)
                and self.user_proposed_first_summary(obj, user)
            ):
                return True
            elif obj.approved is True:
                return False
            return user == obj.proposed_by
        return True

    def is_first_summary(self, obj):
        return (obj.approved is True) and (obj.approved_by is None)

    def user_proposed_first_summary(self, obj, user):
        return (obj.paper.uploaded_by == user) and (obj.proposed_by == user)


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
