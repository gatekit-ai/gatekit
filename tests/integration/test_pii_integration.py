"""Clean functional integration tests for PII plugin using ProcessingPipeline.

All assertions use PipelineOutcome and stage outcomes instead of legacy decision.allowed.
"""

import pytest
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest, MCPResponse
from gatekit.plugins.interfaces import PipelineOutcome


@pytest.mark.asyncio
async def test_pii_block_mode_requests():
    config = {
        "security": {
            "_global": [
                {
                    "handler": "basic_pii_filter",
                    "enabled": True,
                    "config": {
                        "action": "block",
                        "pii_types": {"email": {"enabled": True}},
                    },
                }
            ]
        },
        "auditing": {"_global": []},
    }
    manager = PluginManager(config)
    await manager.load_plugins()
    # Blocked request
    req_block = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="block-1",
        params={"name": "test_tool", "arguments": {"data": "Reach user@example.com"}},
    )
    pipe_block = await manager.process_request(req_block)
    assert pipe_block.pipeline_outcome == PipelineOutcome.BLOCKED
    assert any(s.outcome.value == "blocked" for s in pipe_block.stages)
    # Allowed clean request
    req_clean = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="clean-1",
        params={"name": "test_tool", "arguments": {"data": "No PII here"}},
    )
    pipe_clean = await manager.process_request(req_clean)
    assert pipe_clean.pipeline_outcome == PipelineOutcome.ALLOWED


@pytest.mark.asyncio
async def test_pii_audit_only_mode():
    config = {
        "security": {
            "_global": [
                {
                    "handler": "basic_pii_filter",
                    "enabled": True,
                    "config": {
                        "action": "audit_only",
                        "pii_types": {"email": {"enabled": True}},
                    },
                }
            ]
        },
        "auditing": {"_global": []},
    }
    manager = PluginManager(config)
    await manager.load_plugins()
    req = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="audit-1",
        params={"name": "test_tool", "arguments": {"data": "user@example.com"}},
    )
    pipe = await manager.process_request(req)
    assert pipe.pipeline_outcome == PipelineOutcome.ALLOWED


@pytest.mark.asyncio
async def test_pii_redact_mode_request_modification():
    config = {
        "security": {
            "_global": [
                {
                    "handler": "basic_pii_filter",
                    "enabled": True,
                    "config": {
                        "action": "redact",
                        "pii_types": {"email": {"enabled": True}},
                    },
                }
            ]
        },
        "auditing": {"_global": []},
    }
    manager = PluginManager(config)
    await manager.load_plugins()
    req = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="redact-req-1",
        params={"name": "test_tool", "arguments": {"data": "Email user@example.com"}},
    )
    pipe = await manager.process_request(req)
    assert pipe.pipeline_outcome == PipelineOutcome.MODIFIED
    mod_stage = next((s for s in pipe.stages if s.outcome.value == "modified"), None)
    assert mod_stage and mod_stage.result.modified_content is not None
    redacted = mod_stage.result.modified_content.params["arguments"]["data"]
    assert "[EMAIL REDACTED by Gatekit]" in redacted


@pytest.mark.asyncio
async def test_pii_redact_mode_response_redaction():
    config = {
        "security": {
            "_global": [
                {
                    "handler": "basic_pii_filter",
                    "enabled": True,
                    "config": {
                        "action": "redact",
                        "pii_types": {
                            "email": {"enabled": True},
                            "credit_card": {"enabled": True},
                            "phone": {"enabled": True},
                        },
                    },
                }
            ]
        },
        "auditing": {"_global": []},
    }
    manager = PluginManager(config)
    await manager.load_plugins()
    req = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="redact-resp-1",
        params={"name": "test_tool"},
    )
    resp = MCPResponse(
        jsonrpc="2.0",
        id="redact-resp-1",
        result={"data": "user@example.com 4532015112830366 (555) 123-4567"},
    )
    pipe = await manager.process_response(req, resp)
    assert pipe.pipeline_outcome == PipelineOutcome.MODIFIED
    red_stage = next((s for s in pipe.stages if s.outcome.value == "modified"), None)
    assert red_stage and red_stage.result.modified_content is not None
    data = red_stage.result.modified_content.result["data"]
    assert "[EMAIL REDACTED by Gatekit]" in data
    assert "[CREDIT_CARD REDACTED by Gatekit]" in data
    assert "[PHONE REDACTED by Gatekit]" in data


@pytest.mark.asyncio
async def test_multiple_pii_plugins_response_redaction():
    config = {
        "security": {
            "_global": [
                {
                    "handler": "basic_pii_filter",
                    "enabled": True,
                    "priority": 10,
                    "config": {
                        "action": "redact",
                        "pii_types": {"email": {"enabled": True}},
                    },
                },
                {
                    "handler": "basic_pii_filter",
                    "enabled": True,
                    "priority": 20,
                    "config": {
                        "action": "redact",
                        "pii_types": {
                            "phone": {"enabled": True},
                            "credit_card": {"enabled": True},
                        },
                    },
                },
            ]
        },
        "auditing": {"_global": []},
    }
    manager = PluginManager(config)
    await manager.load_plugins()
    req = MCPRequest(
        jsonrpc="2.0", method="tools/call", id="multi-1", params={"name": "test_tool"}
    )
    resp = MCPResponse(
        jsonrpc="2.0",
        id="multi-1",
        result={"data": "user@example.com (555) 123-4567 4532015112830366"},
    )
    pipe = await manager.process_response(req, resp)
    assert pipe.pipeline_outcome == PipelineOutcome.MODIFIED
    # Collect all modified stages (sequential plugin modifications)
    modified_stages = [s for s in pipe.stages if s.outcome.value == "modified"]
    assert len(modified_stages) >= 1  # At least one modification expected
    # Final content reflects cumulative modifications from all plugins
    final_resp = pipe.final_content
    assert final_resp is not None and isinstance(final_resp.result, dict)
    data = final_resp.result.get("data", "")
    # All three PII types should be redacted after both plugins run
    assert "[EMAIL REDACTED by Gatekit]" in data
    assert "[PHONE REDACTED by Gatekit]" in data
    assert "[CREDIT_CARD REDACTED by Gatekit]" in data
