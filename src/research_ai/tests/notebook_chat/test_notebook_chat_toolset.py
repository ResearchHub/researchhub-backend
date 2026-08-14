from django.test import SimpleTestCase

from research_ai.services.agent import Tool
from research_ai.services.notebook_chat.toolset import compose_notebook_toolset
from research_ai.services.researcher_profile.openalex_tools import (
    GET_WORK_ABSTRACT,
    GET_WORK_FULLTEXT,
    SEARCH_WORK_FULLTEXT,
    SUBMIT_PROFILE,
)


def _tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=name,
        input_schema={"type": "object"},
        handler=lambda _args: {},
    )


class _Tools:
    def __init__(self, *names: str):
        self._names = names

    def build_tools(self) -> list[Tool]:
        return [_tool(name) for name in self._names]


class NotebookToolsetCompositionTests(SimpleTestCase):
    def test_legacy_fulltext_reader_is_excluded_defensively(self):
        # Arrange: simulate an older OpenAlex registry that still offers both
        # focused retrieval and the whole-text tool.
        openalex = _Tools(
            GET_WORK_ABSTRACT,
            SEARCH_WORK_FULLTEXT,
            GET_WORK_FULLTEXT,
            SUBMIT_PROFILE,
        )

        # Act
        toolset = compose_notebook_toolset(
            note_toolset=_Tools("read_note"),
            grant_toolset=_Tools("search_grants"),
            openalex_toolset=openalex,
            web_search_toolset=_Tools("web_search"),
        )

        # Assert
        self.assertIn(GET_WORK_ABSTRACT, toolset.names)
        self.assertIn(SEARCH_WORK_FULLTEXT, toolset.names)
        self.assertNotIn(GET_WORK_FULLTEXT, toolset.names)
        self.assertNotIn(SUBMIT_PROFILE, toolset.names)

    def test_provider_native_tool_is_not_registered_locally(self):
        # Act
        toolset = compose_notebook_toolset(
            note_toolset=_Tools("read_note"),
            grant_toolset=_Tools(),
            openalex_toolset=_Tools(),
            web_search_toolset=_Tools("web_search"),
            native_tool_names=frozenset({"web_search"}),
        )

        # Assert
        self.assertEqual(toolset.names, ["read_note"])
