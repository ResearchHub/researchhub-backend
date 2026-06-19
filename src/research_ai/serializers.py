from datetime import datetime, time

from django.utils import timezone
from rest_framework import serializers

from paper.serializers import PaperSerializer
from research_ai.constants import (
    EXPERT_FINDER_DEFAULT_STATE,
    ExpertiseLevel,
    Gender,
    Region,
)
from research_ai.models import (
    EmailTemplate,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    SearchExpert,
)
from research_ai.services.expert_display import ExpertDisplay
from research_ai.services.expert_outreach_history_service import (
    build_expert_outreach_history_map,
    serialize_expert_outreach_history,
)
from research_ai.services.invited_experts_service import (
    EDITOR_SORT_FIELDS,
    default_overview_date_range,
)
from research_ai.utils import trimmed_str
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
    state = serializers.CharField(default=EXPERT_FINDER_DEFAULT_STATE)
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
        attrs["state"] = attrs.get("state", EXPERT_FINDER_DEFAULT_STATE)
        attrs["gender"] = attrs.get("gender") or Gender.ALL_GENDERS
        return attrs


class ExpertSearchCreateSerializer(serializers.Serializer):
    """POST body for ``/expert-finder/searches/``."""

    unified_document_id = serializers.IntegerField(required=True)
    additional_context = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=ADDITIONAL_CONTEXT_MAX_LENGTH,
    )
    name = serializers.CharField(required=False, allow_blank=True, max_length=512)
    input_type = serializers.ChoiceField(
        choices=ExpertSearch.InputType.choices,
        required=True,
    )
    config = ExpertSearchConfigSerializer(required=False, default=dict)
    excluded_search_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
    )

    def validate(self, attrs):
        raw_ids = attrs.get("excluded_search_ids") or []
        norm_ids: list[int] = []
        seen: set[int] = set()
        for x in raw_ids:
            if x not in seen:
                seen.add(x)
                norm_ids.append(int(x))
        attrs["excluded_search_ids"] = norm_ids
        attrs["config"] = attrs.get("config") or {}
        return attrs


class ExpertSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    honorific = serializers.CharField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    middle_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    name_suffix = serializers.CharField(allow_blank=True)
    academic_title = serializers.CharField(allow_blank=True)
    affiliation = serializers.CharField(allow_blank=True)
    expertise = serializers.CharField(allow_blank=True)
    email = serializers.CharField(allow_blank=True)
    notes = serializers.CharField(allow_blank=True)
    sources = serializers.ListField(required=False, allow_null=True)
    last_email_sent_at = serializers.DateTimeField(allow_null=True)
    emailed_for_current_document = serializers.SerializerMethodField()
    emailed_on_other_documents = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    def _outreach_history_for(self, obj):
        by_email = self.context.get("expert_outreach_by_email") or {}
        email = ExpertDisplay.normalize_email(getattr(obj, "email", "") or "")
        return by_email.get(email)

    def get_emailed_for_current_document(self, obj):
        history = self._outreach_history_for(obj)
        if history is None:
            return None
        return serialize_expert_outreach_history(history)[
            "emailed_for_current_document"
        ]

    def get_emailed_on_other_documents(self, obj):
        history = self._outreach_history_for(obj)
        if history is None:
            return []
        return serialize_expert_outreach_history(history)[
            "emailed_on_other_documents"
        ]

    def get_display_name(self, obj):
        return ExpertDisplay.display_name_for(obj)


class ExpertUpdateSerializer(serializers.ModelSerializer):
    """PATCH body for ``/expert-finder/experts/<id>/``."""

    class Meta:
        model = Expert
        fields = [
            "email",
            "honorific",
            "first_name",
            "middle_name",
            "last_name",
            "name_suffix",
            "academic_title",
            "affiliation",
            "expertise",
            "notes",
        ]
        extra_kwargs = {
            "email": {"required": False},
            "honorific": {"required": False},
            "first_name": {"required": False},
            "middle_name": {"required": False},
            "last_name": {"required": False},
            "name_suffix": {"required": False},
            "academic_title": {"required": False},
            "affiliation": {"required": False},
            "expertise": {"required": False},
            "notes": {"required": False},
        }

    def validate_email(self, value):
        email = ExpertDisplay.normalize_email(value)
        if not email:
            raise serializers.ValidationError("This field may not be blank.")
        qs = Expert.objects.filter(email__iexact=email)
        if self.instance is not None:
            qs = qs.exclude(id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError(
                "An expert with this email already exists."
            )
        return email

    def validate(self, attrs):
        attrs = super().validate(attrs)
        capped_fields = {
            "honorific": 64,
            "first_name": 255,
            "middle_name": 255,
            "last_name": 255,
            "name_suffix": 64,
            "academic_title": 255,
        }
        for field, max_len in capped_fields.items():
            if field in attrs:
                attrs[field] = trimmed_str(attrs[field], max_len=max_len)
        for field in ("affiliation", "expertise", "notes"):
            if field in attrs:
                attrs[field] = trimmed_str(attrs[field])
        return attrs


class ManualExpertCreateSerializer(serializers.Serializer):
    """POST body for ``/expert-finder/searches/<id>/experts/`` (manual entry).

    Email is required; rest are optional. Existing emails are upserted (not
    rejected), unlike :class:`ExpertUpdateSerializer` which forbids duplicates.
    """

    email = serializers.EmailField(required=True, allow_blank=False)
    honorific = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    middle_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    name_suffix = serializers.CharField(required=False, allow_blank=True)
    academic_title = serializers.CharField(required=False, allow_blank=True)
    affiliation = serializers.CharField(required=False, allow_blank=True)
    expertise = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        email = ExpertDisplay.normalize_email(value)
        if not email:
            raise serializers.ValidationError("This field may not be blank.")
        return email

    def validate(self, attrs):
        attrs = super().validate(attrs)
        capped_fields = {
            "honorific": 64,
            "first_name": 255,
            "middle_name": 255,
            "last_name": 255,
            "name_suffix": 64,
            "academic_title": 255,
        }
        for field, max_len in capped_fields.items():
            if field in attrs:
                attrs[field] = trimmed_str(attrs[field], max_len=max_len)
        for field in ("affiliation", "expertise", "notes"):
            if field in attrs:
                attrs[field] = trimmed_str(attrs[field])
        return attrs


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


def _get_user_with_author_payload(user):
    """
    Build ``{ user_id, author }`` for a ``User``.
    Returns ``None`` if ``user`` is None.
    """
    if user is None:
        return None
    author = getattr(user, "author_profile", None)
    author_data = ResearchAIAuthorSerializer(author).data if author else None
    return {"user_id": user.id, "author": author_data}


def _get_created_by_payload(obj):
    """
    Build { user_id: int, author: {...} } for list/detail responses.
    """
    return _get_user_with_author_payload(obj.created_by)


def resolve_work_for_unified_document(unified_doc, context=None):
    """
    Resolve a unified document to work payload (paper or post) using paper/post
    serializers.
    Returns None if resolution fails (no document, unknown type, or serialization
        error).
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


class ExpertSearchListItemSerializer(serializers.ModelSerializer):
    """List row: search metadata (use detail ``experts`` for full expert list)."""

    search_id = serializers.IntegerField(source="id", read_only=True)
    created_by = serializers.SerializerMethodField()
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
            "excluded_search_ids",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    def get_created_by(self, obj):
        return _get_created_by_payload(obj)


class ExpertSearchDetailSerializer(serializers.ModelSerializer):
    """Detail: experts from ``SearchExpert`` / ``Expert``."""

    search_id = serializers.IntegerField(source="id", read_only=True)
    created_by = serializers.SerializerMethodField()
    experts = serializers.SerializerMethodField()
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
            "experts",
            "expert_count",
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

    def get_experts(self, obj):
        # Surface manually-added experts first; ties fall back to position.
        qs = (
            SearchExpert.objects.filter(expert_search_id=obj.id)
            .select_related("expert")
            .order_by("-expert__is_manually_added", "position")
        )
        experts = [se.expert for se in qs]
        outreach_by_email = build_expert_outreach_history_map(
            expert_emails=[e.email for e in experts],
            current_unified_document_id=obj.unified_document_id,
        )

        return ExpertSerializer(
            experts,
            many=True,
            context={
                **self.context,
                "expert_outreach_by_email": outreach_by_email,
            },
        ).data

    def get_report_urls(self, obj):
        out = {}
        if obj.report_pdf_url:
            out["pdf"] = obj.report_pdf_url
        if obj.report_csv_url:
            out["csv"] = obj.report_csv_url
        return out or None


class InvitedExpertStatsFilterSerializer(serializers.Serializer):
    """Shared date/document filters for invited-expert stats endpoints."""

    unified_document_id = serializers.IntegerField(required=False, allow_null=True)
    start = serializers.DateField(required=False, allow_null=True)
    end = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        start_date = attrs.get("start")
        end_date = attrs.get("end")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise serializers.ValidationError(
                {"end": "Must be greater than or equal to start."}
            )

        initial = self.initial_data or {}
        has_start = "start" in initial and initial.get("start") not in (None, "")
        has_end = "end" in initial and initial.get("end") not in (None, "")

        tz = timezone.get_current_timezone()
        if not has_start and not has_end:
            default_start, default_end = default_overview_date_range()
            attrs["start"] = default_start
            attrs["end"] = default_end
        else:
            if start_date is not None:
                attrs["start"] = timezone.make_aware(
                    datetime.combine(start_date, time.min), tz
                )
            if end_date is not None:
                attrs["end"] = timezone.make_aware(
                    datetime.combine(end_date, time.max), tz
                )
        return attrs


class InvitedExpertOverviewQuerySerializer(InvitedExpertStatsFilterSerializer):
    """Query params for GET expert-finder overview."""

    editor_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class ExpertFinderExpertsListQuerySerializer(InvitedExpertOverviewQuerySerializer):
    """Query params for GET expert-finder experts/."""

    registered = serializers.BooleanField(required=False, default=False)
    limit = serializers.IntegerField(required=False, default=20, min_value=1)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate_limit(self, value):
        return min(100, max(1, value if value is not None else 20))


class InvitedExpertEditorsOverviewQuerySerializer(InvitedExpertStatsFilterSerializer):
    """Query params for GET expert-finder editors-overview."""

    limit = serializers.IntegerField(required=False, default=5, min_value=1)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    sort_by = serializers.CharField(required=False, default="experts_total")
    sort_order = serializers.ChoiceField(
        required=False,
        default="desc",
        choices=["asc", "desc"],
    )
    min_searches = serializers.IntegerField(required=False, default=1, min_value=1)

    def validate_sort_by(self, value):
        sort_by = (value or "experts_total").strip()
        if sort_by not in EDITOR_SORT_FIELDS:
            raise serializers.ValidationError(
                f"Must be one of: {', '.join(sorted(EDITOR_SORT_FIELDS))}."
            )
        return sort_by

    def validate_limit(self, value):
        return min(50, max(1, value if value is not None else 5))


class InvitedExpertOverviewSerializer(serializers.Serializer):
    """Response body for expert-finder overview (counts)."""

    experts_total = serializers.IntegerField(read_only=True)
    experts_signed_up = serializers.IntegerField(read_only=True)
    emails_generated = serializers.IntegerField(read_only=True)
    emails_sent = serializers.IntegerField(read_only=True)
    emails_bounced = serializers.IntegerField(read_only=True)
    emails_opened = serializers.IntegerField(read_only=True)
    proposals_opened = serializers.IntegerField(read_only=True)


class InvitedExpertOverviewSummarySerializer(serializers.Serializer):
    searches_total = serializers.IntegerField(read_only=True)
    searches_completed = serializers.IntegerField(read_only=True)
    searches_failed = serializers.IntegerField(read_only=True)
    searches_pending = serializers.IntegerField(read_only=True)
    signup_rate = serializers.FloatField(read_only=True, allow_null=True)
    email_send_rate = serializers.FloatField(read_only=True, allow_null=True)
    open_rate = serializers.FloatField(read_only=True, allow_null=True)
    bounce_rate = serializers.FloatField(read_only=True, allow_null=True)


class InvitedExpertEditorRowSerializer(serializers.Serializer):
    editor = serializers.JSONField(allow_null=True)
    searches_total = serializers.IntegerField(read_only=True)
    searches_completed = serializers.IntegerField(read_only=True)
    experts_total = serializers.IntegerField(read_only=True)
    experts_signed_up = serializers.IntegerField(read_only=True)
    emails_generated = serializers.IntegerField(read_only=True)
    emails_sent = serializers.IntegerField(read_only=True)
    emails_opened = serializers.IntegerField(read_only=True)
    emails_bounced = serializers.IntegerField(read_only=True)
    proposals_outreach_count = serializers.IntegerField(read_only=True)
    emails_sent_by_proposal = serializers.DictField(
        child=serializers.IntegerField(),
        read_only=True,
    )
    signup_rate = serializers.FloatField(read_only=True, allow_null=True)
    open_rate = serializers.FloatField(read_only=True, allow_null=True)
    bounce_rate = serializers.FloatField(read_only=True, allow_null=True)


class InvitedExpertEditorsOverviewSerializer(serializers.Serializer):
    items = InvitedExpertEditorRowSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True)
    offset = serializers.IntegerField(read_only=True)
    sort_by = serializers.CharField(read_only=True)
    sort_order = serializers.CharField(read_only=True)


class ExpertFinderListItemSerializer(ExpertSerializer):
    """Expert row for GET expert-finder experts/ with registered RH user as author."""

    registered_user = serializers.SerializerMethodField()

    def get_registered_user(self, obj):
        return _get_user_with_author_payload(obj.registered_user)


class ExpertSearchSubmitResponseSerializer(serializers.Serializer):
    search_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()
    sse_url = serializers.URLField(allow_null=True)


class GenerateEmailRequestSerializer(serializers.Serializer):
    """
    Request body for POST /expert-finder/generate-email/.
    The view resolves the expert by email.
    """

    expert_search_id = serializers.IntegerField()
    expert_email = serializers.EmailField()
    template = serializers.CharField(required=False, allow_null=True)
    template_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        return _apply_generate_template_rules(attrs, self.initial_data)


class BulkGenerateEmailExpertSerializer(serializers.Serializer):
    """
    One expert in a bulk generate request.
    The view resolves expert data by email against the search.
    """

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
    """
    Request for POST /expert-finder/emails/preview/. Send existing generated emails to
    current user.
    """

    generated_email_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )
    reply_to = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
        max_length=10,
    )


class SendEmailRequestSerializer(serializers.Serializer):
    """Request for POST /expert-finder/emails/send/."""

    generated_email_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=100,
    )
    reply_to = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
        max_length=10,
    )
    cc = serializers.ListField(
        child=serializers.EmailField(),
        required=False,
        default=list,
    )


class InviteRfpApplicantsSerializer(serializers.Serializer):
    """Request for POST /expert-finder/rfp/<grant_id>/invite-applicants/."""

    emails = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
        max_length=100,
    )
    reply_to = serializers.EmailField(required=False, allow_null=True)
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
            "opened_at",
            "open_count",
            "bounced_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "opened_at",
            "open_count",
            "bounced_at",
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
