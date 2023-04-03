from rest_framework.permissions import BasePermission


class CanSetAsAcceptedAnswer(BasePermission):
    message = "Invalid base permission"

    def has_object_permission(self, request, view, obj):
        user = request.user
        parent = obj.parent

        if parent:
            parent_creator = parent.created_by
            if parent_creator == user:
                return True

        # If the comment is a top level comment
        if not parent:
            document_creator = obj.thread.content_object.created_by
            if document_creator == user:
                return True

        return False
