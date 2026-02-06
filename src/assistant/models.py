import uuid

from django.db import models

from utils.models import DefaultModel


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
            if data.get("status") == "complete"
        }

    def get_required_fields(self) -> list:
        """Get list of required fields based on role."""
        if self.role == self.RESEARCHER:
            return ["title", "description", "topic_ids"]
        else:  # FUNDER
            return ["title", "description", "amount", "topic_ids"]

    def check_completion(self) -> bool:
        """Check if all required fields are complete."""
        required = self.get_required_fields()
        complete_fields = self.get_complete_fields()
        return all(field in complete_fields for field in required)
