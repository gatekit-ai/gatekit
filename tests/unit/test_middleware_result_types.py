"""Tests for unified PluginResult type."""

import pytest
from gatekit.plugins.interfaces import PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse


def test_plugin_result_basic():
    """Test basic PluginResult creation."""
    result = PluginResult(reason="test")
    assert result.allowed is None  # Default for middleware behavior
    assert result.reason == "test"
    assert result.metadata == {}
    assert result.modified_content is None
    assert result.completed_response is None


def test_plugin_result_with_security_decision():
    """Test PluginResult with security decision."""
    result = PluginResult(allowed=True, reason="Allowed by policy")
    assert result.allowed is True
    assert result.reason == "Allowed by policy"

    result = PluginResult(allowed=False, reason="Blocked by policy")
    assert result.allowed is False
    assert result.reason == "Blocked by policy"


def test_plugin_result_with_modified_content():
    """Test PluginResult with modified content."""
    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    result = PluginResult(modified_content=request, reason="Modified request")
    assert result.modified_content == request
    assert result.completed_response is None
    assert result.allowed is None  # No security decision


def test_plugin_result_with_completed_response():
    """Test PluginResult with completed response."""
    response = MCPResponse(jsonrpc="2.0", id=1, result={})
    result = PluginResult(completed_response=response, reason="Handled directly")
    assert result.completed_response == response
    assert result.modified_content is None
    assert result.allowed is None  # No security decision


def test_plugin_result_cannot_have_both():
    """Test that PluginResult cannot have both modified_content and completed_response."""
    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    response = MCPResponse(jsonrpc="2.0", id=1, result={})

    with pytest.raises(ValueError, match="Cannot set both"):
        PluginResult(modified_content=request, completed_response=response)


def test_plugin_result_with_metadata():
    """Test PluginResult with metadata."""
    result = PluginResult(allowed=True, reason="test", metadata={"key": "value"})
    assert result.metadata == {"key": "value"}


def test_plugin_result_security_with_modification():
    """Test PluginResult can have both security decision and modification."""
    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    result = PluginResult(
        allowed=True, modified_content=request, reason="Allowed but modified"
    )
    assert result.allowed is True
    assert result.modified_content == request
    assert result.reason == "Allowed but modified"


def test_plugin_result_none_allowed_semantics():
    """Test that allowed=None means no security decision was made."""
    # This is the default for middleware behavior
    result = PluginResult(reason="Just observing")
    assert result.allowed is None

    # Explicitly setting to None
    result = PluginResult(allowed=None, reason="No decision")
    assert result.allowed is None
