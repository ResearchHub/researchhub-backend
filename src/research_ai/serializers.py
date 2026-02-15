from rest_framework import serializers

from research_ai.models import ExpertSearch, GeneratedEmail


class ExpertSearchConfigSerializer(serializers.Serializer):

    expert_count = serializers.IntegerField(default=10, min_value=5, max_value=20)
    expertise_level = serializers.CharField(default="All Levels")
    region = serializers.CharField(default="All Regions")
    state = serializers.CharField(default="All States")
    gender = serializers.CharField(default="All Genders", required=False)

    # Frontend compatibility
    expertCount = serializers.IntegerField(required=False, min_value=5, max_value=20)
    expertiseLevel = serializers.CharField(required=False)
    genderPreference = serializers.CharField(required=False)

    def to_internal_value(self, data):
        # Prefer snake_case from API, fall back to camelCase
        if data.get("expert_count") is None and data.get("expertCount") is not None:
            data = dict(data)
            data["expert_count"] = data["expertCount"]
        if (
            data.get("expertise_level") is None
            and data.get("expertiseLevel") is not None
        ):
            data = dict(data)
            data["expertise_level"] = data["expertiseLevel"]
        if data.get("gender") is None and data.get("genderPreference") is not None:
            data = dict(data)
            data["gender"] = data["genderPreference"]
        return super().to_internal_value(data)

    def validate(self, attrs):
        expert_count = attrs.get("expert_count") or attrs.get("expertCount") or 10
        attrs["expert_count"] = expert_count
        attrs["expertise_level"] = (
            attrs.get("expertise_level") or attrs.get("expertiseLevel") or "All Levels"
        )
        attrs["region"] = attrs.get("region", "All Regions")
        attrs["state"] = attrs.get("state", "All States")
        attrs["gender"] = (
            attrs.get("gender") or attrs.get("genderPreference") or "All Genders"
        )
        return attrs


class ExpertSearchCreateSerializer(serializers.Serializer):

    unified_document_id = serializers.IntegerField(required=False, allow_null=True)
    query = serializers.CharField(required=False, allow_blank=True)
    input_type = serializers.ChoiceField(
        choices=ExpertSearch.InputType.choices,
        default=ExpertSearch.InputType.ABSTRACT,
    )
    config = ExpertSearchConfigSerializer(required=False, default=dict)
    excluded_expert_names = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
    excludedExpertNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )

    def to_internal_value(self, data):
        if isinstance(data, dict) and data.get("excluded_expert_names") is None:
            data = dict(data)
            if data.get("excludedExpertNames") is not None:
                data["excluded_expert_names"] = data["excludedExpertNames"]
        return super().to_internal_value(data)

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
        excluded = attrs.get("excluded_expert_names") or []
        if attrs.get("excludedExpertNames"):
            excluded = list(attrs["excludedExpertNames"])
        attrs["excluded_expert_names"] = excluded
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


class ExpertSearchSerializer(serializers.ModelSerializer):

    search_id = serializers.IntegerField(source="id", read_only=True)
    expert_names = serializers.SerializerMethodField()
    report_urls = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source="created_date", read_only=True)
    updated_at = serializers.DateTimeField(source="updated_date", read_only=True)

    class Meta:
        model = ExpertSearch
        fields = [
            "search_id",
            "query",
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


class ExpertSearchSubmitResponseSerializer(serializers.Serializer):

    search_id = serializers.IntegerField()
    status = serializers.CharField()
    message = serializers.CharField()
    sse_url = serializers.URLField(allow_null=True)


class GeneratedEmailSerializer(serializers.ModelSerializer):
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
            "created_date",
            "updated_date",
        ]
        read_only_fields = ["id", "created_date", "updated_date"]
