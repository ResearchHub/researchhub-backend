from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_expert_finder.permissions import ResearchAIPermission
from ai_expert_finder.serializers import (
    EmailTemplateCreateSerializer,
    EmailTemplateSerializer,
    EmailTemplateUpdateSerializer,
)
from ai_expert_finder.services.email_template_service import (
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from user.permissions import IsModerator, UserIsEditor


class TemplateListView(APIView):
    """
    GET  /api/ai_expert_finder/expert-finder/templates/ - List templates.
    POST /api/ai_expert_finder/expert-finder/templates/ - Create template.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = list_templates()
        total = qs.count()
        items = list(qs[offset : offset + limit])
        ser = EmailTemplateSerializer(items, many=True)
        return Response(
            {
                "templates": ser.data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    def post(self, request):
        ser = EmailTemplateCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # Normalize optional strings to empty string for model
        create_data = {
            "name": (data.get("name") or "").strip(),
            "email_subject": (data.get("email_subject") or "").strip(),
            "email_body": (data.get("email_body") or "").strip(),
        }
        template = create_template(request.user, **create_data)
        out = EmailTemplateSerializer(template)
        return Response(out.data, status=status.HTTP_201_CREATED)


class TemplateDetailView(APIView):
    """
    GET/PATCH/DELETE /api/ai_expert_finder/expert-finder/templates/<template_id>/.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def _get_template(self, request, template_id):
        try:
            tid = int(template_id)
        except (ValueError, TypeError):
            return None, Response(
                {"detail": "Invalid template ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        template = get_template(tid)
        if not template:
            return None, Response(
                {"detail": "Template not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return template, None

    def get(self, request, template_id):
        template, err = self._get_template(request, template_id)
        if err:
            return err
        ser = EmailTemplateSerializer(template)
        return Response(ser.data)

    def patch(self, request, template_id):
        template, err = self._get_template(request, template_id)
        if err:
            return err
        ser = EmailTemplateUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # Build update dict: only include provided fields
        update_data = {}
        for field in (
            "name",
            "email_subject",
            "email_body",
        ):
            if field in data:
                val = data[field]
                update_data[field] = (val or "").strip() if val is not None else ""
        template, not_found = update_template(template_id, **update_data)
        if not_found:
            return Response(
                {"detail": not_found},
                status=status.HTTP_404_NOT_FOUND,
            )
        out = EmailTemplateSerializer(template)
        return Response(out.data)

    def delete(self, request, template_id):
        template, err = self._get_template(request, template_id)
        if err:
            return err
        delete_template(template_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
