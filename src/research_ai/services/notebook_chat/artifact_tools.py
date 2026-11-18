"""Artifact tools for the notebook and assistant chats.

``create_artifact`` makes a standalone piece of content the user views beside
the chat -- an HTML page, a React component, an SVG, a Mermaid diagram, a
Markdown document or code -- and ``update_artifact`` revises one, by exact
find-and-replace edits or a full rewrite. Each write is a new version.
``read_artifact`` returns a version's content, for an artifact made in an
earlier turn. The tools only reach artifacts made in this chat.

Results carry the artifact's id, kind, title and version, never its content
back: the model wrote it, and the activity feed reads these fields to show
the artifact.
"""

import logging

from research_ai.models import AgentConversation, Artifact
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.artifact_service import (
    ArtifactEdit,
    ArtifactError,
    ArtifactService,
)

logger = logging.getLogger(__name__)

CREATE_ARTIFACT = "create_artifact"
UPDATE_ARTIFACT = "update_artifact"
READ_ARTIFACT = "read_artifact"

_NOT_FOUND = "no artifact with that id in this chat"

_KIND_HELP = (
    "html: a complete page (inline CSS and JS; scripts may load from "
    "cdnjs.cloudflare.com, cdn.jsdelivr.net or unpkg.com). react: one "
    "component as its module's default export, styled with Tailwind classes; "
    "react, recharts, lucide-react, d3 and lodash can be imported. svg: one "
    "<svg> element. mermaid: Mermaid diagram source. markdown: a document. "
    "code: source code in `language`."
)


class ArtifactToolset:
    def __init__(
        self,
        *,
        conversation: AgentConversation,
        execution=None,
        service: ArtifactService | None = None,
    ):
        self._conversation = conversation
        self._execution = execution
        self._service = service or ArtifactService()

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=CREATE_ARTIFACT,
                description=(
                    "Create an artifact: standalone content the user views and "
                    "downloads in a panel beside the chat, such as an "
                    "interactive visualization, a diagram, a small tool, or a "
                    "long standalone document or script. Content is rendered "
                    "in an isolated sandbox with no network access beyond the "
                    f"listed script hosts. {_KIND_HELP}"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "A short, specific name.",
                        },
                        "kind": {
                            "type": "string",
                            "enum": list(Artifact.Kind.values),
                        },
                        "language": {
                            "type": "string",
                            "description": (
                                "For kind code: the language, e.g. python."
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": "The artifact's full content.",
                        },
                    },
                    "required": ["title", "kind", "content"],
                },
                handler=self._create,
                # The content streams into the panel while it is written.
                eager_input_streaming=True,
            ),
            Tool(
                name=UPDATE_ARTIFACT,
                description=(
                    "Revise an artifact made in this chat, as a new version. "
                    "Prefer edits: each replaces old_text, which must occur "
                    "exactly once in the current version, with new_text, in "
                    "order. Send content instead only to rewrite most of it. "
                    "Pass title only to rename it."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "integer"},
                        "edits": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old_text": {"type": "string"},
                                    "new_text": {"type": "string"},
                                },
                                "required": ["old_text", "new_text"],
                            },
                        },
                        "content": {
                            "type": "string",
                            "description": "The whole new content.",
                        },
                        "title": {"type": "string"},
                    },
                    "required": ["artifact_id"],
                },
                handler=self._update,
            ),
            Tool(
                name=READ_ARTIFACT,
                description=(
                    "Read an artifact made in this chat: its latest version, "
                    "or the version you name. Read it before updating an "
                    "artifact you did not write or change in this turn."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "integer"},
                        "version": {"type": "integer"},
                    },
                    "required": ["artifact_id"],
                },
                handler=self._read,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _create(self, args: dict) -> dict:
        try:
            artifact = self._service.create(
                self._conversation,
                kind=args.get("kind"),
                title=args.get("title"),
                content=args.get("content"),
                language=args.get("language") or "",
                execution=self._execution,
            )
        except ArtifactError as exc:
            return {"error": str(exc)}
        return _summary(artifact)

    def _update(self, args: dict) -> dict:
        artifact = self._service.in_conversation(
            self._conversation, args.get("artifact_id")
        )
        if artifact is None:
            return {"error": _NOT_FOUND}
        edits = args.get("edits")
        if edits is not None:
            if not isinstance(edits, list) or not all(
                isinstance(edit, dict)
                and isinstance(edit.get("old_text"), str)
                and isinstance(edit.get("new_text"), str)
                for edit in edits
            ):
                return {"error": "edits must be a list of {old_text, new_text}"}
            edits = [ArtifactEdit(edit["old_text"], edit["new_text"]) for edit in edits]
        try:
            self._service.update(
                artifact,
                content=args.get("content"),
                edits=edits,
                title=args.get("title"),
                execution=self._execution,
            )
        except ArtifactError as exc:
            return {"error": str(exc)}
        return _summary(artifact)

    def _read(self, args: dict) -> dict:
        artifact = self._service.in_conversation(
            self._conversation, args.get("artifact_id")
        )
        if artifact is None:
            return {"error": _NOT_FOUND}
        number = args.get("version")
        if number is not None and (
            isinstance(number, bool) or not isinstance(number, int)
        ):
            return {"error": "version must be an integer"}
        version = self._service.version(artifact, number)
        if version is None:
            return {
                "error": (
                    f"no version {number}; versions are 1 to {artifact.latest_version}"
                )
            }
        return {
            **_summary(artifact),
            "version": version.number,
            "latest_version": artifact.latest_version,
            "language": artifact.language,
            "content": version.content,
        }


def _summary(artifact: Artifact) -> dict:
    return {
        "artifact_id": artifact.id,
        "kind": artifact.kind,
        "title": artifact.title,
        "version": artifact.latest_version,
    }


def build_artifacts_notice(artifacts) -> str | None:
    """The notice naming a chat's artifacts; ``None`` for none.

    Opens each turn's prompt, like the created-notes notice, so the model can
    find an artifact from an earlier turn without the system prompt changing.
    """
    listed = "; ".join(
        f'artifact {artifact.id} ("{artifact.title}", {artifact.kind}, '
        f"version {artifact.latest_version})"
        for artifact in artifacts
    )
    if not listed:
        return None
    return (
        "[Notice from the system, not the user: this chat has made these "
        f"artifacts: {listed}.]"
    )
