"""Answer Model Context Protocol (MCP) requests with ResearchHub's agent tools.

Implements the stateless 2026-07-28 revision over Streamable HTTP: each request
names its protocol version in ``_meta`` and mirrors it, the method, and any tool
name in headers, so no session or handshake carries over between requests.
"""

import json
from collections.abc import Mapping

from django.contrib.auth.models import AnonymousUser

from research_ai.services.agent import Toolset
from research_ai.services.notebook_chat import GrantSearchToolset
from user.models import User

PROTOCOL_VERSION = "2026-07-28"

HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

_SUPPORTED_VERSIONS = [PROTOCOL_VERSION]
_SERVER_INFO = {"name": "com.researchhub/researchhub", "version": "1.0.0"}
_SERVER_CARD_SCHEMA = (
    "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"
)
# Discovery and the tool list are the same for every caller.
_PUBLIC_CACHE = {"ttlMs": 60 * 60 * 1000, "cacheScope": "public"}
_DISCOVERY = {
    "supportedVersions": _SUPPORTED_VERSIONS,
    "capabilities": {"tools": {}},
    **_PUBLIC_CACHE,
}


class McpError(Exception):
    """A JSON-RPC error answered in place of a result."""

    def __init__(self, code: int, message: str, **data: object) -> None:
        """Hold the JSON-RPC error object, with ``data`` only when given."""
        super().__init__(message)
        self.code = code
        self.payload = {"code": code, "message": message}
        if data:
            self.payload["data"] = data


def answer_mcp_request(
    message: dict, *, headers: Mapping[str, str], user: User | AnonymousUser
) -> dict:
    """Return the result of a validated JSON-RPC request, or raise ``McpError``."""
    _validate_headers(message, headers)
    toolset = GrantSearchToolset(user=user).as_toolset()
    method = message["method"]
    if method == "server/discover":
        result = _DISCOVERY
    elif method == "tools/list":
        result = _list_tools(toolset)
    elif method == "tools/call":
        result = _call_tool(toolset, message["params"])
    else:
        raise McpError(METHOD_NOT_FOUND, f"Method not found: {method}")
    return {
        "resultType": "complete",
        **result,
        "_meta": {"io.modelcontextprotocol/serverInfo": _SERVER_INFO},
    }


def describe_server_card(endpoint_url: str) -> dict:
    """Describe the MCP endpoint at ``endpoint_url`` for discovery before connecting."""
    return {
        "$schema": _SERVER_CARD_SCHEMA,
        **_SERVER_INFO,
        "description": "Search open research funding opportunities on ResearchHub.",
        "remotes": [
            {
                "type": "streamable-http",
                "url": endpoint_url,
                "supportedProtocolVersions": _SUPPORTED_VERSIONS,
            }
        ],
    }


def _validate_headers(message: dict, headers: Mapping[str, str]) -> None:
    """Reject headers that disagree with the body, or an unsupported version."""
    params = message["params"]
    version = params["_meta"].get("io.modelcontextprotocol/protocolVersion")
    _require_header(headers, "MCP-Protocol-Version", version)
    if version not in _SUPPORTED_VERSIONS:
        raise McpError(
            UNSUPPORTED_PROTOCOL_VERSION,
            "Unsupported protocol version",
            supported=_SUPPORTED_VERSIONS,
            requested=version,
        )
    _require_header(headers, "Mcp-Method", message["method"])
    if message["method"] == "tools/call":
        _require_header(headers, "Mcp-Name", params.get("name"))


def _require_header(headers: Mapping[str, str], name: str, body_value: object) -> None:
    """Raise a header mismatch unless ``name`` is sent and equals ``body_value``."""
    value = headers.get(name)
    if value is None or value != body_value:
        raise McpError(HEADER_MISMATCH, f"{name} header does not match the body")


def _list_tools(toolset: Toolset) -> dict:
    """List every tool with the JSON Schema of its arguments."""
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in toolset.tools
        ],
        **_PUBLIC_CACHE,
    }


def _call_tool(toolset: Toolset, params: dict) -> dict:
    """Run the named tool, flagging a failed run with ``isError``."""
    name = params["name"]
    if toolset.get(name) is None:
        raise McpError(INVALID_PARAMS, f"Unknown tool: {name}")
    output, _ = toolset.dispatch(name, params["arguments"])
    return {
        "content": [{"type": "text", "text": json.dumps(output)}],
        "isError": "error" in output,
    }
