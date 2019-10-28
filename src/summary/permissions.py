from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class ProposeSummaryEdit(RuleBasedPermission):
    message = 'Not enough reputation to propose summary edit.'

    def satisfies_rule(self, request):
        if request.method == RequestMethods.POST:
            return request.user.reputation >= 5
        return True


class UpdateOrDeleteSummaryEdit(AuthorizationBasedPermission):
    message = 'Action not permitted.'

    def is_authorized(self, request, view, obj):
        if (request.method == RequestMethods.PUT) or (
            request.method == RequestMethods.PATCH
        ) or (request.method == RequestMethods.DELETE):
            # TODO: Revisit this.
            #
            # One paradigm says that a summary "edit" is always a new proposed
            # summary and should create a new proposed edit in the database via
            # POST request. This means that a PUT or PATCH should ONLY be used
            # if a user needs to update their proposed edit which has not yet
            # been approved.
            #
            # Does this paradigm meet our needs?
            # If not, let's agree on a new one.
            #
            # That will determine if the below code should be commented out or
            # not.
            #
            # if obj.approved is True:
            #     return False
            return request.user == obj.proposed_by
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
