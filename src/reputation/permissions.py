from datetime import datetime

import pytz
from django.contrib.contenttypes.models import ContentType
from rest_framework.permissions import BasePermission

from reputation.models import Bounty
from researchhub.settings import DIST_WHITELIST
from researchhub_document.models import ResearchhubUnifiedDocument
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
        if obj.item_content_type == ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        ):  # for question bounties, the question creator can control all bounties
            return obj.item.created_by == request.user
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
