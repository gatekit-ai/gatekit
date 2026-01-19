"""Convenience factories for MCP messages in integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from gatekit.protocol.messages import MCPNotification, MCPRequest, MCPResponse


_request_counter = 0


def _next_id(prefix: str) -> str:
    global _request_counter
    _request_counter += 1
    return f"{prefix}-{_request_counter}"


def make_tools_call(name: str, arguments: Dict[str, Any] | None = None) -> MCPRequest:
    return MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id=_next_id("call"),
        params={"name": name, "arguments": arguments or {}},
    )


def make_tools_list_request() -> MCPRequest:
    return MCPRequest(
        jsonrpc="2.0",
        method="tools/list",
        id=_next_id("list"),
        params={"all": True},
    )


def make_simple_response(request: MCPRequest, result: Dict[str, Any] | None = None) -> MCPResponse:
    return MCPResponse(
        jsonrpc="2.0",
        id=request.id,
        result=result or {"message": "ok"},
    )


def make_notification(method: str, params: Dict[str, Any] | None = None) -> MCPNotification:
    return MCPNotification(jsonrpc="2.0", method=method, params=params or {})


def load_request_fixture(name: str) -> Dict[str, Any]:
    path = Path("tests/fixtures/request_samples") / f"{name}.json"
    return json.loads(path.read_text())


__all__ = [
    "make_tools_call",
    "make_tools_list_request",
    "make_simple_response",
    "make_notification",
    "load_request_fixture",
]
