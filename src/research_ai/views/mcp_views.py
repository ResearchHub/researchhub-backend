"""MCP endpoint through which AI agents call ResearchHub's tools directly.

Agents connect here without loading the site; the web app's WebMCP tools are a
separate, browser-only surface that exists only while a page is open.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.serializers import McpRequestSerializer
from research_ai.services.mcp_service import (
    METHOD_NOT_FOUND,
    McpError,
    answer_mcp_request,
    describe_server_card,
)


class ServerCardRenderer(JSONRenderer):
    """JSON under the MCP Server Card media type, for clients that ask for it."""

    media_type = "application/mcp-server-card+json"


class McpView(APIView):
    """
    Answer MCP JSON-RPC requests over Streamable HTTP.

    Open to anonymous agents, who see only public content, under the default
    anonymous throttle.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        """Answer one JSON-RPC request with its result or error."""
        serializer = McpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        try:
            result = answer_mcp_request(
                message, headers=request.headers, user=request.user
            )
        except McpError as error:
            return Response(
                {**reply, "error": error.payload},
                status=(
                    status.HTTP_404_NOT_FOUND
                    if error.code == METHOD_NOT_FOUND
                    else status.HTTP_400_BAD_REQUEST
                ),
            )
        return Response({**reply, "result": result})


class McpServerCardView(APIView):
    """Describe the MCP endpoint so agents can find it before connecting."""

    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, ServerCardRenderer]

    def get(self, request: Request) -> Response:
        """Return the server card, readable by browsers on any origin."""
        card = describe_server_card(request.build_absolute_uri(reverse("mcp")))
        return Response(card, headers={"Access-Control-Allow-Origin": "*"})
