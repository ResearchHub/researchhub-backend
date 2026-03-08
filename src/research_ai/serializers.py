from rest_framework import serializers

from feed.serializers import SimpleAuthorSerializer
from paper.serializers import PaperSerializer
from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import EmailTemplate, ExpertSearch, GeneratedEmail
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.serializers import ResearchhubPostSerializer


class ExpertSearchConfigSerializer(serializers.Serializer):

    expert_count = serializers.IntegerField(default=10, min_value=5, max_value=100)
    expertise_level = serializers.ListField(
        child=serializers.ChoiceField(choices=ExpertiseLevel.choices),
        required=False,
        default=list,
        allow_empty=True,
    )
    region = serializers.ChoiceField(
        choices=Region.choices,
        default=Region.ALL_REGIONS,
    )
    state = serializers.CharField(default="All States")
    gender = serializers.ChoiceField(
        choices=Gender.choices,
        default=Gender.ALL_GENDERS,
        required=False,
    )

    def validate(self, attrs):
        expert_count = attrs.get("expert_count", 10)
        attrs["expert_count"] = expert_count
        expertise_level = attrs.get("expertise_level") or []
        if not isinstance(expertise_level, list):
            expertise_level = [expertise_level] if expertise_level else []
        if not expertise_level or (
            len(expertise_level) == 1
            and expertise_level[0] == ExpertiseLevel.ALL_LEVELS
        ):
            attrs["expertise_level"] = [ExpertiseLevel.ALL_LEVELS]
        else:
            attrs["expertise_level"] = list(expertise_level)
        attrs["region"] = attrs.get("region") or Region.ALL_REGIONS
        attrs["state"] = attrs.get("state", "All States")
        attrs["gender"] = attrs.get("gender") or Gender.ALL_GENDERS
        return attrs


class ExpertSearchCreateSerializer(serializers.Serializer):

    unified_document_id = serializers.IntegerField(required=False, allow_null=True)
    query = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=512)
    input_type = serializers.ChoiceField(
        choices=ExpertSearch.InputType.choices,
        required=False,
    )
    config = ExpertSearchConfigSerializer(required=False, default=dict)
    excluded_expert_names = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )

    def validate(self, attrs):
        unified_document_id = attrs.get("unified_document_id")
        query = attrs.get("query") or ""
        if not unified_document_id and not query.strip():
            raise serializers.ValidationError(
                "Provide either unified_document_id or query."
            )
        if unified_document_id and query.strip():
            raise serializers.ValidationError(
                "Provide either unified_document_id or query, not both."
            )
        if unified_document_id is not None and attrs.get("input_type") is None:
            raise serializers.ValidationError(
                {"input_type": "This field is required when using a document."}
            )
        attrs["excluded_expert_names"] = attrs.get("excluded_expert_names") or []
        attrs["config"] = attrs.get("config") or {}
        return attrs


class ExpertResultSerializer(serializers.Serializer):

    name = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    affiliation = serializers.CharField(allow_blank=True)
    expertise = serializers.CharField(allow_blank=True)
    email = serializers.CharField()
    notes = serializers.CharField(allow_blank=True, required=False)
    sources = serializers.ListField(required=False, allow_null=True)


def resolve_work_for_unified_document(unified_doc, context=None):
    """
    Resolve a unified document to work payload (paper or post) using paper/post serializers.
    Returns None if resolution fails (no document, unknown type, or serialization error).
    """
    if not unified_doc:
        return None
    context = context or {}
    try:
        doc = unified_doc.get_document()
        if doc is None:
            return None
        if unified_doc.document_type == PAPER:
            data = PaperSerializer(doc, context=context).data
            data["type"] = "paper"
            data["unified_document_id"] = unified_doc.id
            return data
        data = ResearchhubPostSerializer(doc, context=context).data
        data["type"] = "post"
        data["unified_document_id"] = unified_doc.id
        return data
    except Exception:
        return None


def _resolve_expert_search_work(expert_search, context=None):
    """
    Resolve ExpertSearch.unified_document to work payload using paper/post serializers.
    Returns None if no unified_document or resolution fails.
    """
    unified_doc = getattr(expert_search, "unified_document", None)
    return resolve_work_for_unified_document(unified_doc, context=context)


class ExpertSearchSerializer(serializers.ModelSerializer):

    search_id = serializers.IntegerField(source="id", read_only=True)
    expert_names = serializers.SerializerMethodField()
    report_urls = serializers.SerializerMethodField()
    work = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created_date", read_only=True)
    updated_at = serializers.DateTimeField(source="updated_date", read_only=True)

    class Meta:
        model = ExpertSearch
        fields = [
            "search_id",
            "name",
            "query",
            "work",
            "input_type",
            "config",
            "excluded_expert_names",
            "llm_model",
            "status",
            "progress",
            "current_step",
            "expert_results",
            "expert_count",
            "expert_names",
            "report_urls",
            "report_pdf_url",
            "report_csv_url",
            "processing_time",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = fields

    def get_work(self, obj):
        return _resolve_expert_search_work(obj, context=self.context)

    def get_expert_names(self, obj):
        """List of expert names for FE excluder (SearchHistoryExcluder)."""
        if not obj.expert_results:
            return []
        return [e.get("name") or "" for e in obj.expert_results if e.get("name")]

    def get_report_urls(self, obj):
        out = {}
        if obj.report_pdf_url:
            out["pdf"] = obj.report_pdf_url
        if obj.report_csv_url:
            out["csv"] = obj.report_csv_url
        return out or None


class ExpertSearchListItemSerializer(serializers.ModelSerializer):

    search_id = serializers.IntegerField(source="id", read_only=True)
    expert_names = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created_date", read_only=True)

    class Meta:
        model = ExpertSearch
        fields = [
            "search_id",
            "name",
            "query",
            "status",
            "expert_count",
            "expert_names",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    def get_expert_names(self, obj):
        if not obj.expert_results:
            return []
        return [e.get("name") or "" for e in obj.expert_results if e.get("name")]


class InvitedExpertSerializer(serializers.Serializer):

    author = serializers.SerializerMethodField()
    expert_search_id = serializers.SerializerMethodField()
    generated_email_id = serializers.SerializerMethodField()
    invited_at = serializers.DateTimeField(source="created_date", read_only=True)

    def get_author(self, obj):
        author = getattr(obj.user, "author_profile", None)
        if author is None:
            return None
        return SimpleAuthorSerializer(author).data

    def get_expert_search_id(self, obj):
        return obj.expert_search_id

    def get_generated_email_id(self, obj):
        return obj.generated_email_id


class ExpertSearchSubmitResponseSerializer(serializers.Serializer):

    search_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()
    sse_url = serializers.URLField(allow_null=True)


class GenerateEmailRequestSerializer(serializers.Serializer):
    """Request body for POST /expert-finder/generate-email/. Expert data is resolved from expert_results by email.
    outreach_context comes from the template when loaded by template_id."""

    expert_search_id = serializers.IntegerField()
    expert_email = serializers.EmailField()
    template = serializers.CharField(required=True)
    template_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_template(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("template is required")
        return value.strip()


class BulkGenerateEmailExpertSerializer(serializers.Serializer):
    """One expert in a bulk generate request; expert data is resolved from expert_results by email."""

    expert_email = serializers.EmailField()


class BulkGenerateEmailRequestSerializer(serializers.Serializer):
    """Request body for POST /expert-finder/generate-emails-bulk/."""

    expert_search_id = serializers.IntegerField()
    experts = serializers.ListField(
        child=BulkGenerateEmailExpertSerializer(),
        min_length=1,
        max_length=100,
    )
    template = serializers.CharField(required=True)
    template_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_template(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("template is required")
        return value.strip()


class PreviewEmailRequestSerializer(serializers.Serializer):
    """Request for POST /expert-finder/emails/preview/. Send existing generated emails to current user."""

    generated_email_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )


class SendEmailRequestSerializer(serializers.Serializer):
    """Request for POST /expert-finder/emails/send/."""

    generated_email_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )
    reply_to = serializers.EmailField(required=False, allow_blank=True, default="")
    cc = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
        default=list,
    )


class GeneratedEmailSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(source="created_date", read_only=True)
    updated_at = serializers.DateTimeField(source="updated_date", read_only=True)

    class Meta:
        model = GeneratedEmail
        fields = [
            "id",
            "expert_search",
            "expert_name",
            "expert_title",
            "expert_affiliation",
            "expert_email",
            "expertise",
            "email_subject",
            "email_body",
            "template",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class GeneratedEmailCreateUpdateSerializer(serializers.ModelSerializer):
    """Create or update GeneratedEmail (e.g. mark sent, edit body)."""

    class Meta:
        model = GeneratedEmail
        fields = [
            "expert_search",
            "expert_name",
            "expert_title",
            "expert_affiliation",
            "expert_email",
            "expertise",
            "email_subject",
            "email_body",
            "template",
            "status",
            "notes",
        ]
        extra_kwargs = {
            "expert_search": {"required": False},
            "expert_name": {"required": False},
            "expert_title": {"required": False},
            "expert_affiliation": {"required": False},
            "expert_email": {"required": False},
            "expertise": {"required": False},
            "email_subject": {"required": False},
            "email_body": {"required": False},
            "template": {"required": False},
            "status": {"required": False},
            "notes": {"required": False},
        }


class EmailTemplateSerializer(serializers.ModelSerializer):
    """List/detail serializer for EmailTemplate."""

    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "created_by",
            "name",
            "contact_name",
            "contact_title",
            "contact_institution",
            "contact_email",
            "contact_phone",
            "contact_website",
            "outreach_context",
            "template_type",
            "email_subject",
            "email_body",
            "created_date",
            "updated_date",
        ]
        read_only_fields = ["id", "created_by", "created_date", "updated_date"]


class EmailTemplateCreateSerializer(serializers.Serializer):
    """Create a new EmailTemplate. name required; rest optional."""

    name = serializers.CharField(max_length=255, allow_blank=False)
    contact_name = serializers.CharField(max_length=255, required=False, default="")
    contact_title = serializers.CharField(max_length=255, required=False, default="")
    contact_institution = serializers.CharField(
        max_length=512, required=False, default=""
    )
    contact_email = serializers.CharField(max_length=255, required=False, default="")
    contact_phone = serializers.CharField(max_length=64, required=False, default="")
    contact_website = serializers.CharField(max_length=512, required=False, default="")
    outreach_context = serializers.CharField(
        required=False, default="", allow_blank=True
    )
    template_type = serializers.ChoiceField(
        choices=EmailTemplate.TemplateType.choices,
        required=False,
        default=EmailTemplate.TemplateType.PROMPT_CONTEXT,
    )
    email_subject = serializers.CharField(required=False, default="", allow_blank=True)
    email_body = serializers.CharField(required=False, default="", allow_blank=True)


class EmailTemplateUpdateSerializer(serializers.Serializer):
    """Partial update for EmailTemplate."""

    name = serializers.CharField(max_length=255, required=False, allow_blank=False)
    contact_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    contact_title = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    contact_institution = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )
    contact_email = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    contact_phone = serializers.CharField(
        max_length=64, required=False, allow_blank=True
    )
    contact_website = serializers.CharField(
        max_length=512, required=False, allow_blank=True
    )
    outreach_context = serializers.CharField(required=False, allow_blank=True)
    email_subject = serializers.CharField(required=False, allow_blank=True)
    email_body = serializers.CharField(required=False, allow_blank=True)
