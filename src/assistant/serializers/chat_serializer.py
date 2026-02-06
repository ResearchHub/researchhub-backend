from rest_framework import serializers

from assistant.models import AssistantSession, FieldStatus


class StructuredInputSerializer(serializers.Serializer):
    """Serializer for structured input from UI components."""

    field = serializers.CharField(
        help_text="Field name being set (e.g., 'author_ids', 'topic_ids', 'note_id')"
    )
    value = serializers.JSONField(
        help_text="The value for the field (can be array, string, number, etc.)"
    )


class ChatRequestSerializer(serializers.Serializer):
    """Serializer for chat request payload."""

    session_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Existing session ID. If not provided, creates a new session.",
    )
    role = serializers.ChoiceField(
        choices=AssistantSession.ROLE_CHOICES,
        required=False,
        help_text="Required when creating a new session: 'researcher' or 'funder'",
    )
    message = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="The user's message text",
    )
    structured_input = StructuredInputSerializer(
        required=False,
        allow_null=True,
        help_text="Optional structured data from UI components (author select, topic select, etc.)",
    )
    is_resume = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set to true when resuming a session. Skips adding to history and returns a progress summary.",
    )

    def validate(self, attrs):
        """Validate that role is provided when session_id is not."""
        session_id = attrs.get("session_id")
        role = attrs.get("role")

        if not session_id and not role:
            raise serializers.ValidationError(
                {"role": "Role is required when creating a new session."}
            )

        return attrs


class QuickReplySerializer(serializers.Serializer):
    """Serializer for quick reply options."""

    label = serializers.CharField(help_text="Button text to display")
    value = serializers.CharField(
        allow_null=True,
        help_text="Message to send when tapped. Null means focus text input.",
    )


class FieldUpdateSerializer(serializers.Serializer):
    """Serializer for field update data."""

    status = serializers.ChoiceField(
        choices=FieldStatus.CHOICES,
        help_text="Status of the field: 'empty', 'ai_suggested', or 'complete'",
    )
    value = serializers.JSONField(
        help_text="The field value (string, number, array, etc.)"
    )


class ChatResponseSerializer(serializers.Serializer):
    """Serializer for chat response payload."""

    session_id = serializers.UUIDField(help_text="The session ID")
    message = serializers.CharField(help_text="Bot's conversational response")
    follow_up = serializers.CharField(
        allow_null=True,
        help_text="Optional additional formatted content. When input_type is 'rich_editor', contains HTML for the editor.",
    )
    input_type = serializers.CharField(
        allow_null=True,
        help_text="Type of inline component to show: author_lookup, topic_select, nonprofit_lookup, rich_editor, final_review",
    )
    editor_field = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="When input_type is 'rich_editor', names the field the editor content maps to (e.g. 'description')",
    )
    note_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the note associated with this session, or null",
    )
    quick_replies = QuickReplySerializer(
        many=True,
        allow_null=True,
        help_text="Suggested quick reply buttons",
    )
    field_updates = serializers.DictField(
        child=FieldUpdateSerializer(),
        allow_null=True,
        help_text="Updates to field state",
    )
    complete = serializers.BooleanField(
        help_text="Whether all required fields are collected"
    )
    payload = serializers.JSONField(
        allow_null=True,
        help_text="Final payload for submission (only when complete)",
    )


class SessionDetailSerializer(serializers.Serializer):
    """Serializer for session state (GET by ID). No conversation history."""

    session_id = serializers.UUIDField(source="id", help_text="The session ID")
    role = serializers.CharField(help_text="Session role: 'researcher' or 'funder'")
    note_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the note associated with this session",
    )
    field_state = serializers.JSONField(
        help_text="Current state of collected fields",
    )
    is_complete = serializers.BooleanField(
        help_text="Whether all required fields are collected",
    )
    created_date = serializers.DateTimeField(
        help_text="When the session was created",
    )
    updated_date = serializers.DateTimeField(
        help_text="When the session was last updated",
    )


class SessionListSerializer(serializers.Serializer):
    """Serializer for session list items (GET list)."""

    session_id = serializers.UUIDField(source="id", help_text="The session ID")
    role = serializers.CharField(help_text="Session role: 'researcher' or 'funder'")
    note_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the note associated with this session",
    )
    is_complete = serializers.BooleanField(
        help_text="Whether all required fields are collected",
    )
    message_count = serializers.SerializerMethodField(
        help_text="Number of messages in the conversation",
    )
    created_date = serializers.DateTimeField(
        help_text="When the session was created",
    )
    updated_date = serializers.DateTimeField(
        help_text="When the session was last updated",
    )

    def get_message_count(self, obj):
        return len(obj.conversation_history)
