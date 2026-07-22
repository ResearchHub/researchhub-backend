from datetime import UTC, datetime

from django.contrib.contenttypes.models import ContentType
from rest_framework.permissions import BasePermission

from reputation.models import Bounty
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User
from utils.permissions import AuthorizationBasedPermission


class IsFoundationUser(BasePermission):
    message = "Only the ResearchHub Foundation account may perform this action."

    def has_permission(self, request, view):
        return request.user.is_authenticated and User.is_rh_community_account(
            request.user
        )


class UpdateOrDeleteWithdrawal(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        method = request.method
        user = request.user
        if (method == "PUT") or (method == "PATCH") or (method == "DELETE"):
            return user == obj.user
        return True


class AllowWithdrawalIfNotSuspecious(BasePermission):
    message = "Cannot withdraw funds at this time."

    def has_permission(self, request, view):
        return not (
            request.method in ("POST", "PATCH")
            and request.user.is_authenticated
            and (request.user.is_suspended or request.user.probable_spammer)
        )


class UserCanApproveBounty(BasePermission):
    def has_permission(self, request, view):
        method = request.method
        return bool(method == "POST" or method == "DELETE")

    def has_object_permission(self, request, view, obj):
        self.message = "Invalid Bounty user"

        if obj.parent_id:
            obj = obj.parent

        if obj.status not in (Bounty.OPEN, Bounty.ASSESSMENT):
            self.message = "Bounty is closed."
            return False

        now = datetime.now(UTC)
        if obj.status == Bounty.OPEN:
            # During OPEN phase, check expiration_date
            if obj.expiration_date and obj.expiration_date <= now:
                self.message = "Bounty is expired"
                return False
        elif (
            obj.status == Bounty.ASSESSMENT
            and obj.assessment_end_date
            and obj.assessment_end_date <= now
        ):
            # During ASSESSMENT phase, check assessment_end_date
            self.message = "Bounty assessment period has expired"
            return False

        if obj.item_content_type == ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        ):  # for question bounties, the question creator can control all bounties
            return obj.item.created_by == request.user
        return obj.created_by == request.user


class UserCanCancelBounty(BasePermission):
    def has_permission(self, request, view):
        method = request.method
        return bool(method == "POST" or method == "DELETE")

    def has_object_permission(self, request, view, obj):
        self.message = "Invalid Bounty user"

        if obj.parent_id:
            obj = obj.parent

        if obj.status not in (Bounty.OPEN, Bounty.ASSESSMENT):
            self.message = "Bounty is closed."
            return False
        return obj.created_by == request.user
