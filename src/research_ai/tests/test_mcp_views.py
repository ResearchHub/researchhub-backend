"""API tests for the MCP endpoint and its server card."""

import json
from unittest.mock import patch

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APITestCase

from purchase.services.grant_search_service import GrantSearchService
from research_ai.services.mcp_service import (
    HEADER_MISMATCH,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    UNSUPPORTED_PROTOCOL_VERSION,
)
from user.tests.helpers import create_random_authenticated_user

URL = "/api/research_ai/mcp/"


class McpViewTests(APITestCase):
    def _post(
        self,
        method: str,
        *,
        params: dict | None = None,
        version: str = PROTOCOL_VERSION,
        **headers: str,
    ) -> Response:
        """POST a JSON-RPC request whose MCP headers mirror it unless overridden."""
        return self.client.post(
            URL,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {
                    "_meta": {"io.modelcontextprotocol/protocolVersion": version},
                    **(params or {}),
                },
            },
            format="json",
            **{
                "HTTP_MCP_PROTOCOL_VERSION": version,
                "HTTP_MCP_METHOD": method,
                **headers,
            },
        )

    def test_lists_the_grant_tools(self) -> None:
        """tools/list returns each grant tool with its input schema."""
        # Act
        response = self._post("tools/list")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["result"]
        self.assertEqual(result["resultType"], "complete")
        tools = result["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools], ["search_grants", "get_grant_details"]
        )
        self.assertEqual(tools[0]["inputSchema"]["required"], ["query"])

    def test_calls_a_tool_as_the_requesting_user(self) -> None:
        """tools/call runs the named tool for the authenticated user."""
        # Arrange
        user = create_random_authenticated_user("mcp_user")
        self.client.force_authenticate(user)

        # Act
        with patch.object(GrantSearchService, "search", return_value=[]) as search:
            response = self._post(
                "tools/call",
                params={"name": "search_grants", "arguments": {"query": "crispr"}},
                HTTP_MCP_NAME="search_grants",
            )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            {"query": "crispr", "grants": []},
        )
        search.assert_called_once_with(user=user, query="crispr")

    def test_rejects_a_method_header_that_disagrees_with_the_body(self) -> None:
        """An Mcp-Method header naming another method is a header mismatch."""
        # Act
        response = self._post("tools/list", HTTP_MCP_METHOD="tools/call")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], HEADER_MISMATCH)

    def test_rejects_an_unsupported_protocol_version(self) -> None:
        """An unsupported version is refused with the versions the server speaks."""
        # Act
        response = self._post("tools/list", version="2025-11-25")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error = response.json()["error"]
        self.assertEqual(error["code"], UNSUPPORTED_PROTOCOL_VERSION)
        self.assertEqual(
            error["data"],
            {"supported": [PROTOCOL_VERSION], "requested": "2025-11-25"},
        )

    def test_reports_unknown_methods_as_not_found(self) -> None:
        """A method the server does not implement is answered with a 404."""
        # Act
        response = self._post("prompts/list")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["error"]["code"], METHOD_NOT_FOUND)


class McpServerCardViewTests(APITestCase):
    def test_points_agents_to_the_mcp_endpoint(self) -> None:
        """The server card lists the endpoint and is readable from any origin."""
        # Act
        response = self.client.get(f"{URL}server-card/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(
            response.json()["remotes"],
            [
                {
                    "type": "streamable-http",
                    "url": f"http://testserver{URL}",
                    "supportedProtocolVersions": [PROTOCOL_VERSION],
                }
            ],
        )
