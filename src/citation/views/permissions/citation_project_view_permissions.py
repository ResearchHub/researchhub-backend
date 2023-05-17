from rest_framework.permissions import BasePermission

from citation.related_models.citation_project import CitationProject


class UserIsAdminOfProject(BasePermission):
    message = "Permission Denied: Not requestor is not admin of the project"

    def has_permission(
        self,
        request,
        view,
    ):
        requestor = request.user
        if requestor.is_anonymous:
            return False

        target_project = CitationProject.objects.filter(
            id=int(view.kwargs.get("pk"))
        ).first()
        if target_project is not None:
            return target_project.get_is_user_admin(requestor)

        return False
