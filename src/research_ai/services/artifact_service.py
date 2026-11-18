"""Artifacts a chat agent makes: standalone pages, components, diagrams,
documents and code the user views beside the chat.

An artifact belongs to the chat whose agent made it and is private to that
chat's owner. Its content is versioned: creating it writes version 1, and
every update -- a full rewrite or a list of exact find-and-replace edits --
appends the next one, so the user can step back through earlier versions.
Nothing here renders content; the web client shows it in a sandbox.
"""

from dataclasses import dataclass

from django.db import transaction

from research_ai.models import AgentConversation, Artifact, ArtifactVersion

# One version's content. Generous for a page or a component, and well inside
# the tool result backstop, so read_artifact can always return a whole version.
MAX_CONTENT_CHARS = 100_000
MAX_TITLE_CHARS = 255
MAX_LANGUAGE_CHARS = 32


class ArtifactError(ValueError):
    """An artifact write the caller asked for cannot be made, and why."""


@dataclass(frozen=True)
class ArtifactEdit:
    """Replace ``old_text``, which must occur exactly once, with ``new_text``."""

    old_text: str
    new_text: str


def apply_edits(content: str, edits: list[ArtifactEdit]) -> str:
    """``content`` with ``edits`` applied in order.

    Each edit applies to the result of the ones before it. One whose
    ``old_text`` is missing or ambiguous fails the whole list: a partial
    application would leave content neither the model nor the user expects.
    """
    for index, edit in enumerate(edits, start=1):
        if not edit.old_text:
            raise ArtifactError(f"edit {index}: old_text is empty")
        count = content.count(edit.old_text)
        if count == 0:
            raise ArtifactError(
                f"edit {index}: old_text was not found in the current content"
            )
        if count > 1:
            raise ArtifactError(
                f"edit {index}: old_text occurs {count} times; include more "
                "surrounding text so it matches exactly once"
            )
        content = content.replace(edit.old_text, edit.new_text, 1)
    return content


class ArtifactService:
    def create(
        self,
        conversation: AgentConversation,
        *,
        kind: str,
        title: str,
        content: str,
        language: str = "",
        execution=None,
    ) -> Artifact:
        """A new artifact in ``conversation`` with ``content`` as version 1."""
        if kind not in Artifact.Kind.values:
            raise ArtifactError(
                f"kind must be one of: {', '.join(Artifact.Kind.values)}"
            )
        title = _clean_title(title)
        language = " ".join(str(language or "").split())
        if len(language) > MAX_LANGUAGE_CHARS:
            raise ArtifactError(
                f"language is longer than {MAX_LANGUAGE_CHARS} characters"
            )
        _check_content(content)
        with transaction.atomic():
            artifact = Artifact.objects.create(
                conversation=conversation,
                kind=kind,
                title=title,
                language=language if kind == Artifact.Kind.CODE else "",
                latest_version=1,
            )
            ArtifactVersion.objects.create(
                artifact=artifact, number=1, content=content, execution=execution
            )
        return artifact

    def update(
        self,
        artifact: Artifact,
        *,
        content: str | None = None,
        edits: list[ArtifactEdit] | None = None,
        title: str | None = None,
        execution=None,
    ) -> ArtifactVersion:
        """Append a version: ``content`` replaces the whole text, ``edits``
        change the latest version's. Exactly one of the two is required;
        ``title`` optionally renames the artifact too.
        """
        if (content is None) == (edits is None):
            raise ArtifactError("pass exactly one of content or edits")
        if edits is not None and not edits:
            raise ArtifactError("edits is empty")
        new_title = None if title is None else _clean_title(title)
        with transaction.atomic():
            # Locked so two writers cannot both claim the next version number.
            locked = Artifact.objects.select_for_update().get(id=artifact.id)
            if edits is not None:
                current = self.version(locked)
                content = apply_edits(current.content if current else "", edits)
            _check_content(content)
            locked.latest_version += 1
            update_fields = ["latest_version", "updated_date"]
            if new_title is not None:
                locked.title = new_title
                update_fields.append("title")
            locked.save(update_fields=update_fields)
            version = ArtifactVersion.objects.create(
                artifact=locked,
                number=locked.latest_version,
                content=content,
                execution=execution,
            )
        artifact.latest_version = locked.latest_version
        artifact.title = locked.title
        return version

    def in_conversation(
        self, conversation: AgentConversation, artifact_id
    ) -> Artifact | None:
        """Artifact ``artifact_id`` if ``conversation`` made it."""
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
            return None
        return Artifact.objects.filter(
            id=artifact_id, conversation=conversation
        ).first()

    def for_conversation(self, conversation: AgentConversation) -> list[Artifact]:
        """``conversation``'s artifacts, oldest first."""
        return list(Artifact.objects.filter(conversation=conversation).order_by("id"))

    def get_for_user(self, user, artifact_id: int) -> Artifact | None:
        """Artifact ``artifact_id`` if ``user`` owns the chat that made it.

        A removed chat's artifacts go with it.
        """
        return (
            Artifact.objects.select_related("conversation")
            .filter(
                id=artifact_id,
                conversation__user=user,
                conversation__is_removed=False,
            )
            .first()
        )

    def version(
        self, artifact: Artifact, number: int | None = None
    ) -> ArtifactVersion | None:
        """Version ``number`` of ``artifact``, or its latest one."""
        return ArtifactVersion.objects.filter(
            artifact=artifact,
            number=artifact.latest_version if number is None else number,
        ).first()

    def representation(self, artifact: Artifact, version: ArtifactVersion) -> dict:
        """The API shape of ``artifact`` showing ``version``."""
        return {
            "id": artifact.id,
            "conversation_id": artifact.conversation_id,
            "kind": artifact.kind,
            "title": artifact.title,
            "language": artifact.language,
            "latest_version": artifact.latest_version,
            "created_date": artifact.created_date,
            "updated_date": artifact.updated_date,
            "version": {
                "number": version.number,
                "content": version.content,
                "created_date": version.created_date,
            },
        }


def _clean_title(title) -> str:
    cleaned = " ".join(str(title or "").split())
    if not cleaned:
        raise ArtifactError("title is required")
    return cleaned[:MAX_TITLE_CHARS]


def _check_content(content) -> None:
    if not isinstance(content, str) or not content.strip():
        raise ArtifactError("content is empty")
    if len(content) > MAX_CONTENT_CHARS:
        raise ArtifactError(
            f"content is {len(content)} characters, over the "
            f"{MAX_CONTENT_CHARS} limit; make the artifact smaller"
        )
