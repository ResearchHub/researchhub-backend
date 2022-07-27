from datetime import datetime

import pytz
from rest_framework.permissions import BasePermission

from reputation.models import Bounty
from researchhub.settings import DIST_WHITELIST
from utils.http import RequestMethods
from utils.permissions import AuthorizationBasedPermission


class UpdateOrDeleteWithdrawal(AuthorizationBasedPermission):
    message = "Action not permitted."

    def is_authorized(self, request, view, obj):
        method = request.method
        user = request.user
        if (
            (method == RequestMethods.PUT)
            or (method == RequestMethods.PATCH)
            or (method == RequestMethods.DELETE)
        ):
            return user == obj.user
        return True


class DistributionWhitelist(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if user.is_anonymous:
            return False

        if user.email in DIST_WHITELIST:
            return True
        return False


class UserCanApproveBounty(BasePermission):
    def has_permission(self, request, view):
        method = request.method
        if method == RequestMethods.POST or method == RequestMethods.DELETE:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        self.message = "Invalid Bounty user"

        if obj.status != Bounty.OPEN:
            self.message = "Bounty is closed."
            return False
        elif obj.expiration_date <= datetime.now(pytz.UTC):
            self.message = "Bounty is expired"
            return False
        return obj.created_by == request.user


class UserCanCancelBounty(BasePermission):
    def has_permission(self, request, view):
        method = request.method
        if method == RequestMethods.POST or method == RequestMethods.DELETE:
            return True
        return False

    def has_object_permission(self, request, view, obj):
        self.message = "Invalid Bounty user"

        if obj.status != Bounty.OPEN:
            self.message = "Bounty is closed."
            return False
        return obj.created_by == request.user


class SingleBountyOpen(BasePermission):
    message = "User already has open bounty on object"

    def has_permission(self, request, view):
        if view.action == "create":
            data = request.data
            object_id = data.get("item_object_id", None)
            user_has_open_bounty = view.queryset.filter(
                created_by=request.user, status=Bounty.OPEN, item_object_id=object_id
            ).exists()
            return not user_has_open_bounty
        return True
