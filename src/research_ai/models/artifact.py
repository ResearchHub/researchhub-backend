from django.db import models

from utils.models import DefaultModel


class Artifact(DefaultModel):
    """A standalone piece of content a chat agent made: a page, a component, a
    diagram, a document or code the user views beside the chat.

    The content lives in ``ArtifactVersion`` rows: every create or update by
    the agent adds one, so earlier versions stay viewable.
    """

    class Kind(models.TextChoices):
        HTML = "html", "HTML page"
        REACT = "react", "React component"
        SVG = "svg", "SVG image"
        MERMAID = "mermaid", "Mermaid diagram"
        MARKDOWN = "markdown", "Markdown document"
        CODE = "code", "Code"

    conversation = models.ForeignKey(
        "research_ai.AgentConversation",
        on_delete=models.CASCADE,
        related_name="artifacts",
        db_comment="The chat whose agent made the artifact.",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=255)
    language = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="Programming language of a code artifact; blank for other kinds.",
    )
    latest_version = models.PositiveIntegerField(
        default=0,
        db_comment="Number of the newest version; versions are numbered from 1.",
    )

    class Meta:
        db_table = "research_ai_artifact"


class ArtifactVersion(DefaultModel):
    """One immutable revision of an artifact's content."""

    artifact = models.ForeignKey(
        Artifact, on_delete=models.CASCADE, related_name="versions"
    )
    number = models.PositiveIntegerField()
    content = models.TextField()
    execution = models.ForeignKey(
        "research_ai.AgentExecution",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="The chat turn that wrote this version.",
    )

    class Meta:
        db_table = "research_ai_artifact_version"
        constraints = [
            models.UniqueConstraint(
                fields=["artifact", "number"], name="ra_artifact_version_unique"
            )
        ]
