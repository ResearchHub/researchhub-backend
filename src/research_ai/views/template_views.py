from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    EmailTemplateCreateSerializer,
    EmailTemplateSerializer,
    EmailTemplateUpdateSerializer,
)
from research_ai.services.email_template_service import (
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from user.permissions import IsModerator


class TemplateListView(APIView):
    """
    GET  /api/research_ai/expert-finder/templates/ - List templates.
    POST /api/research_ai/expert-finder/templates/ - Create template.
    """

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def get(self, request):
        limit = max(1, min(100, int(request.query_params.get("limit", 20))))
        offset = max(0, int(request.query_params.get("offset", 0)))
        qs = list_templates(request.user)
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
            "contact_name": (data.get("contact_name") or "").strip(),
            "contact_title": (data.get("contact_title") or "").strip(),
            "contact_institution": (data.get("contact_institution") or "").strip(),
            "contact_email": (data.get("contact_email") or "").strip(),
            "contact_phone": (data.get("contact_phone") or "").strip(),
            "contact_website": (data.get("contact_website") or "").strip(),
            "outreach_context": (data.get("outreach_context") or "").strip(),
        }
        template = create_template(request.user, **create_data)
        out = EmailTemplateSerializer(template)
        return Response(out.data, status=status.HTTP_201_CREATED)


class TemplateDetailView(APIView):
    """
    GET/PATCH/DELETE /api/research_ai/expert-finder/templates/<template_id>/.
    """

    permission_classes = [IsAuthenticated, ResearchAIPermission, IsModerator]

    def _get_template(self, request, template_id):
        try:
            tid = int(template_id)
        except (ValueError, TypeError):
            return None, Response(
                {"detail": "Invalid template ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        template = get_template(request.user, tid)
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
            "contact_name",
            "contact_title",
            "contact_institution",
            "contact_email",
            "contact_phone",
            "contact_website",
            "outreach_context",
            "is_active",
        ):
            if field in data:
                val = data[field]
                if field == "is_active":
                    update_data[field] = bool(val)
                else:
                    update_data[field] = (val or "").strip() if val is not None else ""
        template, not_found = update_template(request.user, template_id, **update_data)
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
        delete_template(request.user, template_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
