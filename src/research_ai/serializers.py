from rest_framework import serializers

from feed.serializers import SimpleAuthorSerializer
from paper.serializers import PaperSerializer
from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import EmailTemplate, Expert, ExpertSearch, GeneratedEmail
from research_ai.services.expert_results_payload import get_expert_results_payload
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.serializers import ResearchhubPostSerializer
from user.models import Author

ADDITIONAL_CONTEXT_MAX_LENGTH = 10_000


def _apply_generate_template_rules(attrs, initial_data):
    """
    Expert-finder generate endpoints: explicit JSON null ``template`` requires
    ``template_id`` (fixed path). Other values are stripped; whitespace-only is invalid.
    If ``template`` is omitted from the body, ``attrs`` is unchanged.
    """
    initial = initial_data or {}
    if "template" not in initial:
        return attrs
    raw = initial["template"]
    if raw is None:
        if not attrs.get("template_id"):
            raise serializers.ValidationError(
                {"template_id": "This field is required when template is null."}
            )
        attrs["template"] = None
        return attrs
    s = str(raw).strip()
    if not s:
        raise serializers.ValidationError({"template": "This field may not be blank."})
    attrs["template"] = s
    return attrs


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
    additional_context = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=ADDITIONAL_CONTEXT_MAX_LENGTH,
    )
    name = serializers.CharField(required=False, allow_blank=True, max_length=512)
    input_type = serializers.ChoiceField(
        choices=ExpertSearch.InputType.choices,
        required=False,
    )
    config = ExpertSearchConfigSerializer(required=False, default=dict)
    excluded_search_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
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
        raw_sid = attrs.get("excluded_search_ids") or []
        attrs["excluded_search_ids"] = list(dict.fromkeys(int(x) for x in raw_sid))
        attrs["config"] = attrs.get("config") or {}
        return attrs


class ExpertResultSerializer(serializers.Serializer):

    expert_id = serializers.IntegerField(required=False, allow_null=True)
    honorific = serializers.CharField(allow_blank=True, required=False)
    first_name = serializers.CharField(allow_blank=True, required=False)
    middle_name = serializers.CharField(allow_blank=True, required=False)
    last_name = serializers.CharField(allow_blank=True, required=False)
    name_suffix = serializers.CharField(allow_blank=True, required=False)
    name = serializers.CharField()
    academic_title = serializers.CharField(allow_blank=True, required=False)
    title = serializers.CharField(allow_blank=True, required=False)
    affiliation = serializers.CharField(allow_blank=True)
    expertise = serializers.CharField(allow_blank=True)
    email = serializers.CharField()
    notes = serializers.CharField(allow_blank=True, required=False)
    sources = serializers.ListField(required=False, allow_null=True)
    last_email_sent_at = serializers.DateTimeField(
        required=False, allow_null=True, read_only=True
    )


class ExpertPartialUpdateSerializer(serializers.ModelSerializer):
    """PATCH body for a single Expert (expert-finder canonical contact)."""

    class Meta:
        model = Expert
        fields = [
            "honorific",
            "first_name",
            "middle_name",
            "last_name",
            "name_suffix",
            "academic_title",
            "affiliation",
            "expertise",
            "notes",
            "email",
            "sources",
        ]

    def validate_email(self, value):
        email = (value or "").strip().lower()
        if not email:
            raise serializers.ValidationError("This field may not be blank.")
        qs = Expert.objects.filter(email__iexact=email)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "An expert with this email already exists."
            )
        return email

    def update(self, instance, validated_data):
        if "email" in validated_data:
            validated_data["email"] = (validated_data["email"] or "").strip().lower()
        return super().update(instance, validated_data)


class ResearchAIAuthorSerializer(serializers.ModelSerializer):
    """Author (creator) for research_ai list/detail responses; no nested user."""

    profile_image = serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = ["id", "first_name", "last_name", "profile_image", "headline"]

    def get_profile_image(self, obj):
        try:
            if (
                hasattr(obj, "profile_image")
                and obj.profile_image
                and obj.profile_image.name
            ):
                return obj.profile_image.url
        except Exception:
            pass
        return None


def _get_created_by_payload(obj):
    """
    Build { user_id: int, author: {...} } for list/detail responses.
    """
    created_by = obj.created_by
    author = getattr(created_by, "author_profile", None)
    author_data = ResearchAIAuthorSerializer(author).data if author else None
    return {"user_id": created_by.id, "author": author_data}


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
    created_by = serializers.SerializerMethodField()
    expert_results = serializers.SerializerMethodField()
    expert_names = serializers.SerializerMethodField()
    expert_ids = serializers.SerializerMethodField()
    report_urls = serializers.SerializerMethodField()
    work = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created_date", read_only=True)
    updated_at = serializers.DateTimeField(source="updated_date", read_only=True)

    class Meta:
        model = ExpertSearch
        fields = [
            "search_id",
            "created_by",
            "name",
            "query",
            "additional_context",
            "work",
            "input_type",
            "config",
            "excluded_search_ids",
            "llm_model",
            "status",
            "progress",
            "current_step",
            "expert_results",
            "expert_count",
            "expert_names",
            "expert_ids",
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

    def get_created_by(self, obj):
        return _get_created_by_payload(obj)

    def get_work(self, obj):
        return _resolve_expert_search_work(obj, context=self.context)

    def get_expert_results(self, obj):
        return get_expert_results_payload(obj)

    def get_expert_names(self, obj):
        rows = get_expert_results_payload(obj)
        return [e.get("name") or "" for e in rows if e.get("name")]

    def get_expert_ids(self, obj):
        rows = get_expert_results_payload(obj)
        return [e["expert_id"] for e in rows if e.get("expert_id") is not None]

    def get_report_urls(self, obj):
        out = {}
        if obj.report_pdf_url:
            out["pdf"] = obj.report_pdf_url
        if obj.report_csv_url:
            out["csv"] = obj.report_csv_url
        return out or None


class ExpertSearchListItemSerializer(serializers.ModelSerializer):

    search_id = serializers.IntegerField(source="id", read_only=True)
    created_by = serializers.SerializerMethodField()
    expert_names = serializers.SerializerMethodField()
    expert_ids = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created_date", read_only=True)

    class Meta:
        model = ExpertSearch
        fields = [
            "search_id",
            "created_by",
            "name",
            "query",
            "status",
            "expert_count",
            "expert_names",
            "expert_ids",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    def get_created_by(self, obj):
        return _get_created_by_payload(obj)

    def get_expert_names(self, obj):
        rows = get_expert_results_payload(obj)
        return [e.get("name") or "" for e in rows if e.get("name")]

    def get_expert_ids(self, obj):
        rows = get_expert_results_payload(obj)
        return [e["expert_id"] for e in rows if e.get("expert_id") is not None]


class InvitedExpertSerializer(serializers.Serializer):
    """
    One invited expert row: dict from get_document_invited_rows
    (user, expert_search_id, generated_email_id optional, invited_at) or legacy
    DocumentInvitedExpert-like object with .user and ids.
    """

    author = serializers.SerializerMethodField()
    expert_search_id = serializers.SerializerMethodField()
    generated_email_id = serializers.SerializerMethodField()
    invited_at = serializers.SerializerMethodField()

    def _user(self, obj):
        if isinstance(obj, dict):
            return obj.get("user")
        return getattr(obj, "user", None)

    def get_author(self, obj):
        user = self._user(obj)
        if user is None:
            return None
        author = getattr(user, "author_profile", None)
        if author is None:
            return None
        return SimpleAuthorSerializer(author).data

    def get_expert_search_id(self, obj):
        if isinstance(obj, dict):
            return obj.get("expert_search_id")
        return getattr(obj, "expert_search_id", None)

    def get_generated_email_id(self, obj):
        if isinstance(obj, dict):
            return obj.get("generated_email_id")
        return getattr(obj, "generated_email_id", None)

    def get_invited_at(self, obj):
        if isinstance(obj, dict):
            return obj.get("invited_at")
        return getattr(obj, "created_date", None)


class ExpertSearchSubmitResponseSerializer(serializers.Serializer):

    search_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()
    sse_url = serializers.URLField(allow_null=True)


class GenerateEmailRequestSerializer(serializers.Serializer):
    """Request body for POST /expert-finder/generate-email/. Expert data is resolved from SearchExpert rows by email."""

    expert_search_id = serializers.IntegerField()
    expert_email = serializers.EmailField()
    template = serializers.CharField(required=False, allow_null=True)
    template_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        return _apply_generate_template_rules(attrs, self.initial_data)


class BulkGenerateEmailExpertSerializer(serializers.Serializer):
    """One expert in a bulk generate request; expert data is resolved from SearchExpert rows by email."""

    expert_email = serializers.EmailField()


class BulkGenerateEmailRequestSerializer(serializers.Serializer):
    """Request body for POST /expert-finder/generate-emails-bulk/."""

    expert_search_id = serializers.IntegerField()
    experts = serializers.ListField(
        child=BulkGenerateEmailExpertSerializer(),
        min_length=1,
        max_length=100,
    )
    template = serializers.CharField(required=False, allow_null=True)
    template_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        return _apply_generate_template_rules(attrs, self.initial_data)


class PreviewEmailRequestSerializer(serializers.Serializer):
    """Request for POST /expert-finder/emails/preview/. Send existing generated emails to current user."""

    generated_email_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )
    reply_to = serializers.EmailField(required=True)


class SendEmailRequestSerializer(serializers.Serializer):
    """Request for POST /expert-finder/emails/send/."""

    generated_email_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )
    reply_to = serializers.EmailField(required=True)
    cc = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
        default=list,
    )


class GeneratedEmailSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created_date", read_only=True)
    updated_at = serializers.DateTimeField(source="updated_date", read_only=True)

    class Meta:
        model = GeneratedEmail
        fields = [
            "id",
            "created_by",
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
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "ses_message_id",
        ]

    def get_created_by(self, obj):
        return _get_created_by_payload(obj)


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

    created_by = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "created_by",
            "name",
            "email_subject",
            "email_body",
            "created_date",
            "updated_date",
        ]
        read_only_fields = ["id", "created_by", "created_date", "updated_date"]

    def get_created_by(self, obj):
        return _get_created_by_payload(obj)


class EmailTemplateCreateSerializer(serializers.Serializer):
    """Create a new EmailTemplate. name required; rest optional."""

    name = serializers.CharField(max_length=255, allow_blank=False)
    email_subject = serializers.CharField(required=False, default="", allow_blank=True)
    email_body = serializers.CharField(required=False, default="", allow_blank=True)


class EmailTemplateUpdateSerializer(serializers.Serializer):
    """Partial update for EmailTemplate."""

    name = serializers.CharField(max_length=255, required=False, allow_blank=False)
    email_subject = serializers.CharField(required=False, allow_blank=True)
    email_body = serializers.CharField(required=False, allow_blank=True)
