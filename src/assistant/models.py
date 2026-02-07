import uuid

from django.db import models

from assistant.config import (
    FUNDER_FIELDS,
    FUNDER_REQUIRED,
    RESEARCHER_FIELDS,
    RESEARCHER_REQUIRED,
    FieldStatus,
)
from utils.models import DefaultModel


def _build_initial_field_state(role: str) -> dict:
    """Build initial field state with all fields set to empty."""
    fields = RESEARCHER_FIELDS if role == "researcher" else FUNDER_FIELDS
    return {field: {"status": FieldStatus.EMPTY, "value": ""} for field in fields}


class AssistantSession(DefaultModel):
    """
    Model representing a conversation session with the AI assistant.

    Stores conversation history and field state for creating proposals
    (preregistration posts) or funding opportunities (grants).
    """

    # Role choices
    RESEARCHER = "researcher"
    FUNDER = "funder"

    ROLE_CHOICES = (
        (RESEARCHER, "Researcher"),
        (FUNDER, "Funder"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="assistant_sessions",
        help_text="User who owns this session",
    )

    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        help_text="Whether the user is creating a proposal or funding opportunity",
    )

    conversation_history = models.JSONField(
        default=list,
        help_text="List of messages in the conversation (role, content pairs)",
    )

    field_state = models.JSONField(
        default=dict,
        help_text="Current state of collected fields (field_name: {status, value})",
    )

    is_complete = models.BooleanField(
        default=False,
        help_text="Whether all required fields have been collected",
    )

    note_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ID of the note created by the frontend for this session",
    )

    # Store the final payload when complete
    payload = models.JSONField(
        null=True,
        blank=True,
        help_text="The final assembled payload ready for submission",
    )

    class Meta:
        ordering = ["-created_date"]
        indexes = [
            models.Index(fields=["user", "-created_date"]),
            models.Index(fields=["is_complete"]),
        ]

    def __str__(self):
        return f"Session {self.id} - {self.user} ({self.role})"

    def initialize_field_state(self) -> None:
        """Initialize field state with all fields set to empty based on role."""
        self.field_state = _build_initial_field_state(self.role)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        self.conversation_history.append({"role": role, "content": content})

    def update_field(self, field_name: str, status: str, value) -> None:
        """Update a field in the field state."""
        self.field_state[field_name] = {"status": status, "value": value}

    def get_field_value(self, field_name: str):
        """Get the value of a field from field state."""
        field = self.field_state.get(field_name)
        if field:
            return field.get("value")
        return None

    def get_complete_fields(self) -> dict:
        """Get all fields with 'complete' status."""
        return {
            name: data["value"]
            for name, data in self.field_state.items()
            if data.get("status") == FieldStatus.COMPLETE
        }

    def get_required_fields(self) -> list:
        """Get list of required fields based on role."""
        if self.role == self.RESEARCHER:
            return list(RESEARCHER_REQUIRED)
        else:  # FUNDER
            return list(FUNDER_REQUIRED)

    def check_completion(self) -> bool:
        """Check if all required fields are complete."""
        required = self.get_required_fields()
        complete_fields = self.get_complete_fields()
        return all(field in complete_fields for field in required)

    def get_progress_summary(self) -> str:
        """Get a human-readable summary of field progress."""
        required = set(self.get_required_fields())
        complete = []
        draft = []
        empty = []

        for field_name, data in self.field_state.items():
            status = data.get("status", "empty")
            if status == FieldStatus.COMPLETE:
                complete.append(field_name)
            elif status == FieldStatus.AI_SUGGESTED:
                draft.append(field_name)
            else:
                empty.append(field_name)

        required_complete = [f for f in complete if f in required]
        total_required = len(required)

        parts = [
            f"You've completed {len(required_complete)} of {total_required} required fields"
        ]
        if required_complete:
            names = ", ".join(f.replace("_", " ") for f in required_complete)
            parts.append(f"({names})")

        remaining = required - set(required_complete)
        if remaining:
            names = ", ".join(f.replace("_", " ") for f in remaining)
            parts.append(f". Still needed: {names}")

        if draft:
            names = ", ".join(f.replace("_", " ") for f in draft)
            parts.append(f". In draft: {names}")

        return "".join(parts) + "."
