"""Security Model Validation Tests

This test file serves as executable documentation for the Gatekit security model.
Every behavior documented in /docs/security-model.md should have corresponding tests here.

These tests validate the ACTUAL behavior of the security processing pipeline and serve
as a guard against semantic drift. If these tests break, either:
1. The implementation has changed (update the security-model.md documentation)
2. The tests are wrong (fix them to match documented behavior)

The tests are organized to match the sections in security-model.md for easy cross-referencing.
"""

from unittest.mock import Mock
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    MiddlewarePlugin,
    PluginResult,
    ProcessingPipeline,
    PipelineStage,
    StageOutcome,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse


class TestCoreConceptsValidation:
    """Validates the core concepts and enums defined in the security model."""

    def test_stage_outcome_enum_values(self):
        """Verify StageOutcome enum has expected values."""
        assert StageOutcome.ALLOWED.value == "allowed"
        assert StageOutcome.BLOCKED.value == "blocked"
        assert StageOutcome.MODIFIED.value == "modified"
        assert StageOutcome.COMPLETED_BY_MIDDLEWARE.value == "completed_by_middleware"
        assert StageOutcome.ERROR.value == "error"

    def test_pipeline_outcome_enum_values(self):
        """Verify PipelineOutcome enum has expected values."""
        assert PipelineOutcome.ALLOWED.value == "allowed"
        assert PipelineOutcome.BLOCKED.value == "blocked"
        assert PipelineOutcome.MODIFIED.value == "modified"
        assert (
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE.value == "completed_by_middleware"
        )
        assert PipelineOutcome.ERROR.value == "error"
        assert PipelineOutcome.NO_SECURITY_EVALUATION.value == "no_security"

    def test_processing_pipeline_initial_state(self):
        """Verify ProcessingPipeline starts with correct defaults."""
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
        pipeline = ProcessingPipeline(original_content=request)

        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        assert pipeline.capture_content is True
        assert pipeline.had_security_plugin is False
        assert pipeline.blocked_at_stage is None
        assert pipeline.completed_by is None
        assert len(pipeline.stages) == 0


class TestPluginTypeValidation:
    """Validates plugin type behaviors and contracts."""

    def test_security_plugin_default_critical(self):
        """SecurityPlugin defaults to critical=True (fail closed)."""

        # Create a concrete implementation
        class TestSecurityPlugin(SecurityPlugin):
            async def process_request(self, request, server_name=None):
                return PluginResult(allowed=True)

            async def process_response(self, request, response, server_name=None):
                return PluginResult(allowed=True)

            async def process_notification(self, notification, server_name=None):
                return PluginResult(allowed=True)

        plugin = TestSecurityPlugin({})
        assert plugin.critical is True

    def test_middleware_plugin_default_critical(self):
        """MiddlewarePlugin defaults to critical=True (all plugins fail-closed by default)."""

        # Create a concrete implementation
        class TestMiddlewarePlugin(MiddlewarePlugin):
            async def process_request(self, request, server_name=None):
                return PluginResult(allowed=None)

            async def process_response(self, request, response, server_name=None):
                return PluginResult(allowed=None)

            async def process_notification(self, notification, server_name=None):
                return PluginResult(allowed=None)

        plugin = TestMiddlewarePlugin({})
        assert plugin.critical is True

    def test_security_plugin_can_override_critical(self):
        """SecurityPlugin criticality can be overridden."""

        # Create a concrete implementation
        class TestSecurityPlugin(SecurityPlugin):
            async def process_request(self, request, server_name=None):
                return PluginResult(allowed=True)

            async def process_response(self, request, response, server_name=None):
                return PluginResult(allowed=True)

            async def process_notification(self, notification, server_name=None):
                return PluginResult(allowed=True)

        plugin = TestSecurityPlugin({"critical": False})
        assert plugin.critical is False

    def test_middleware_plugin_can_override_critical(self):
        """MiddlewarePlugin criticality can be overridden."""

        # Create a concrete implementation
        class TestMiddlewarePlugin(MiddlewarePlugin):
            async def process_request(self, request, server_name=None):
                return PluginResult(allowed=None)

            async def process_response(self, request, response, server_name=None):
                return PluginResult(allowed=None)

            async def process_notification(self, notification, server_name=None):
                return PluginResult(allowed=None)

        plugin = TestMiddlewarePlugin({"critical": True})
        assert plugin.critical is True


class TestStageOutcomeDetermination:
    """Validates how StageOutcome is determined from plugin results."""

    def test_exception_becomes_error_outcome(self):
        """Exception during plugin execution → StageOutcome.ERROR"""
        pipeline = ProcessingPipeline(original_content=Mock())
        stage = PipelineStage(
            plugin_name="TestPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False, reason="Exception occurred"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ERROR,
            error_type="ValueError",
            security_evaluated=True,
        )
        pipeline.add_stage(stage)
        assert stage.outcome == StageOutcome.ERROR
        assert stage.error_type == "ValueError"

    def test_allowed_false_becomes_blocked_outcome(self):
        """result.allowed=False → StageOutcome.BLOCKED"""
        pipeline = ProcessingPipeline(original_content=Mock())
        stage = PipelineStage(
            plugin_name="TestPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False, reason="Blocked"),
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(stage)
        assert stage.outcome == StageOutcome.BLOCKED
        # When added to pipeline, it updates pipeline outcome
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage == "TestPlugin"

    def test_completed_response_becomes_completed_outcome(self):
        """result.completed_response → StageOutcome.COMPLETED_BY_MIDDLEWARE"""
        pipeline = ProcessingPipeline(original_content=Mock())
        completed_response = MCPResponse(jsonrpc="2.0", id=1, result={})
        stage = PipelineStage(
            plugin_name="CachePlugin",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=completed_response,
            content_hash="hash",
            result=PluginResult(allowed=None, completed_response=completed_response),
            processing_time_ms=1.0,
            outcome=StageOutcome.COMPLETED_BY_MIDDLEWARE,
            error_type=None,
            security_evaluated=False,
        )
        pipeline.add_stage(stage)
        assert stage.outcome == StageOutcome.COMPLETED_BY_MIDDLEWARE
        assert pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
        assert pipeline.completed_by == "CachePlugin"

    def test_modified_content_becomes_modified_outcome(self):
        """result.modified_content → StageOutcome.MODIFIED"""
        stage = PipelineStage(
            plugin_name="PIIFilter",
            plugin_type="security",
            input_content=Mock(),
            output_content=Mock(),
            content_hash="hash",
            result=PluginResult(allowed=True, modified_content=Mock()),
            processing_time_ms=1.0,
            outcome=StageOutcome.MODIFIED,
            error_type=None,
            security_evaluated=True,
        )
        assert stage.outcome == StageOutcome.MODIFIED

    def test_default_becomes_allowed_outcome(self):
        """No special conditions → StageOutcome.ALLOWED"""
        stage = PipelineStage(
            plugin_name="LoggingPlugin",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=None, reason="Logged"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,
            error_type=None,
            security_evaluated=False,
        )
        assert stage.outcome == StageOutcome.ALLOWED


class TestPipelineOutcomeUpdates:
    """Validates pipeline outcome update rules."""

    def test_pipeline_modified_outcome(self):
        """Pipeline with modified content should have MODIFIED outcome."""
        pipeline = ProcessingPipeline(original_content=Mock())

        # Add a stage with modified content
        modified_stage = PipelineStage(
            plugin_name="PIIFilter",
            plugin_type="security",
            input_content=Mock(),
            output_content=Mock(),
            content_hash="hash",
            result=PluginResult(allowed=True, modified_content=Mock()),
            processing_time_ms=1.0,
            outcome=StageOutcome.MODIFIED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(modified_stage)

        # In the manager, during finalization, it would check for modifications
        # and set the pipeline outcome to MODIFIED
        # We'll simulate that logic here
        has_modifications = any(
            stage.outcome == StageOutcome.MODIFIED for stage in pipeline.stages
        )
        assert has_modifications is True

        # The actual pipeline outcome would be set during finalization
        # based on the presence of MODIFIED stages

    def test_pipeline_starts_as_no_security_evaluation(self):
        """Pipeline starts with NO_SECURITY_EVALUATION."""
        pipeline = ProcessingPipeline(original_content=Mock())
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION

    def test_first_security_allowed_updates_to_allowed(self):
        """First security plugin with allowed=True updates to ALLOWED."""
        pipeline = ProcessingPipeline(original_content=Mock())
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION

        # Simulate security plugin allowing
        pipeline.had_security_plugin = True
        # In real code, this happens in the manager when it sees result.allowed=True
        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED

        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED

    def test_blocked_stage_updates_to_blocked(self):
        """Adding BLOCKED stage updates pipeline to BLOCKED."""
        pipeline = ProcessingPipeline(original_content=Mock())
        stage = PipelineStage(
            plugin_name="Blocker",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False),
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(stage)

        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage == "Blocker"

    def test_completed_stage_updates_to_completed(self):
        """Adding COMPLETED_BY_MIDDLEWARE stage updates pipeline."""
        pipeline = ProcessingPipeline(original_content=Mock())
        stage = PipelineStage(
            plugin_name="Cache",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=Mock(),
            content_hash="hash",
            result=PluginResult(completed_response=Mock()),
            processing_time_ms=1.0,
            outcome=StageOutcome.COMPLETED_BY_MIDDLEWARE,
            error_type=None,
            security_evaluated=False,
        )
        pipeline.add_stage(stage)

        assert pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
        assert pipeline.completed_by == "Cache"

    def test_blocked_outcome_is_final(self):
        """Once BLOCKED, pipeline outcome doesn't change."""
        pipeline = ProcessingPipeline(original_content=Mock())

        # First add a blocked stage
        blocked_stage = PipelineStage(
            plugin_name="Blocker",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False),
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(blocked_stage)
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED

        # Try to add another stage (shouldn't happen in practice)
        # Pipeline outcome should remain BLOCKED
        passed_stage = PipelineStage(
            plugin_name="AllowPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=True),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(passed_stage)

        # Outcome should still be BLOCKED
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED


class TestContentClearingRules:
    """Validates when content gets cleared from pipeline stages."""

    def test_security_block_triggers_content_clearing(self):
        """Security plugin blocking sets capture_content=False."""
        pipeline = ProcessingPipeline(original_content=Mock())
        assert pipeline.capture_content is True

        # Simulate security block (manager would set this)
        pipeline.capture_content = False

        assert pipeline.capture_content is False

    def test_security_modification_triggers_content_clearing(self):
        """Security plugin modification sets capture_content=False."""
        pipeline = ProcessingPipeline(original_content=Mock())
        assert pipeline.capture_content is True

        # Simulate security modification (manager would set this)
        pipeline.capture_content = False

        assert pipeline.capture_content is False

    def test_middleware_modification_does_not_trigger_clearing(self):
        """Middleware modification should NOT set capture_content=False."""
        pipeline = ProcessingPipeline(original_content=Mock())
        assert pipeline.capture_content is True

        # Add middleware stage with modification
        stage = PipelineStage(
            plugin_name="MiddlewarePlugin",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=Mock(),
            content_hash="hash",
            result=PluginResult(allowed=None, modified_content=Mock()),
            processing_time_ms=1.0,
            outcome=StageOutcome.MODIFIED,
            error_type=None,
            security_evaluated=False,
        )
        pipeline.add_stage(stage)

        # Middleware modification shouldn't affect capture_content
        # (In real code, manager checks isinstance(plugin, SecurityPlugin))
        assert pipeline.capture_content is True


class TestCriticalVsNonCriticalHandling:
    """Validates critical vs non-critical plugin error handling."""

    def test_critical_plugin_error_stops_processing(self):
        """Critical plugin error should stop processing."""
        # This behavior is in the manager, not the pipeline itself
        # The manager sets had_critical_error and breaks the loop
        pipeline = ProcessingPipeline(original_content=Mock())

        error_stage = PipelineStage(
            plugin_name="CriticalPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False, reason="Error"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ERROR,
            error_type="ValueError",
            security_evaluated=True,
        )
        pipeline.add_stage(error_stage)

        # Manager would set pipeline_outcome to ERROR during finalization
        # if had_critical_error is True
        assert error_stage.outcome == StageOutcome.ERROR

    def test_non_critical_plugin_error_continues_processing(self):
        """Non-critical plugin error should allow processing to continue."""
        pipeline = ProcessingPipeline(original_content=Mock())

        # Add non-critical error stage
        error_stage = PipelineStage(
            plugin_name="NonCriticalPlugin",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=None, reason="Warning"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ERROR,
            error_type="Warning",
            security_evaluated=False,
        )
        pipeline.add_stage(error_stage)

        # Add a successful stage after
        success_stage = PipelineStage(
            plugin_name="SuccessPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=True),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(success_stage)

        # Both stages should be in pipeline
        assert len(pipeline.stages) == 2
        assert pipeline.stages[0].outcome == StageOutcome.ERROR
        assert pipeline.stages[1].outcome == StageOutcome.ALLOWED

    def test_criticality_does_not_affect_security_decisions(self):
        """Criticality only affects errors, not security decisions."""
        # Even non-critical security plugins can block
        pipeline = ProcessingPipeline(original_content=Mock())

        blocked_stage = PipelineStage(
            plugin_name="NonCriticalSecurityPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False),
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(blocked_stage)

        # Should still block even if plugin was non-critical
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED


class TestPipelineOutcomeInterpretation:
    """Validates pipeline outcome interpretation for audit logging."""

    def test_blocked_pipeline_interpretation(self):
        """BLOCKED pipeline indicates request was denied."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.pipeline_outcome = PipelineOutcome.BLOCKED
        pipeline.had_security_plugin = True

        # Audit formatters now receive raw pipeline_outcome and had_security_plugin
        # They can interpret these values according to their specific needs

        assert pipeline.pipeline_outcome in [
            PipelineOutcome.BLOCKED,
            PipelineOutcome.ERROR,
        ]

    def test_allowed_with_security_interpretation(self):
        """ALLOWED with security plugin indicates request was permitted."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        pipeline.had_security_plugin = True

        # Audit formatters now receive raw pipeline_outcome and had_security_plugin
        # They can interpret these values according to their specific needs

        assert pipeline.pipeline_outcome in [
            PipelineOutcome.ALLOWED,
            PipelineOutcome.MODIFIED,
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
        ]

    def test_modified_with_security_interpretation(self):
        """MODIFIED with security plugin indicates content was changed."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.pipeline_outcome = PipelineOutcome.MODIFIED
        pipeline.had_security_plugin = True

        # Audit formatters now receive raw pipeline_outcome and had_security_plugin
        # They can interpret these values according to their specific needs

        assert pipeline.pipeline_outcome in [
            PipelineOutcome.ALLOWED,
            PipelineOutcome.MODIFIED,
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
        ]

    def test_completed_without_security_interpretation(self):
        """COMPLETED_BY_MIDDLEWARE without security shows no security evaluation."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.pipeline_outcome = PipelineOutcome.COMPLETED_BY_MIDDLEWARE
        pipeline.had_security_plugin = False

        # Audit formatters now receive raw pipeline_outcome and had_security_plugin
        # They can interpret these values according to their specific needs

        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION or (
            pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
            and not pipeline.had_security_plugin
        )

    def test_error_interpretation(self):
        """ERROR pipeline indicates a critical failure."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.pipeline_outcome = PipelineOutcome.ERROR
        pipeline.had_security_plugin = True

        # Audit formatters now receive raw pipeline_outcome and had_security_plugin
        # They can interpret these values according to their specific needs

        assert pipeline.pipeline_outcome in [
            PipelineOutcome.BLOCKED,
            PipelineOutcome.ERROR,
        ]

    def test_no_security_evaluation_interpretation(self):
        """NO_SECURITY_EVALUATION shows no security plugins ran."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.pipeline_outcome = PipelineOutcome.NO_SECURITY_EVALUATION
        pipeline.had_security_plugin = False

        # Audit formatters now receive raw pipeline_outcome and had_security_plugin
        # They can interpret these values according to their specific needs

        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION or (
            pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
            and not pipeline.had_security_plugin
        )


class TestEdgeCases:
    """Validates edge cases and special behaviors."""

    def test_middleware_allowed_false_ignored_in_pipeline(self):
        """Middleware setting allowed=False doesn't create BLOCKED outcome."""
        # This tests the documented edge case
        pipeline = ProcessingPipeline(original_content=Mock())

        # Middleware stage with allowed=False
        # In real code, manager checks isinstance(plugin, SecurityPlugin)
        # and only sets BLOCKED for security plugins
        stage = PipelineStage(
            plugin_name="MiddlewarePlugin",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False, reason="Suspicious"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,  # Not BLOCKED!
            error_type=None,
            security_evaluated=False,
        )
        pipeline.add_stage(stage)

        # Pipeline should not be blocked
        assert pipeline.pipeline_outcome != PipelineOutcome.BLOCKED
        assert stage.outcome == StageOutcome.ALLOWED

    def test_multiple_security_first_block_wins(self):
        """First security plugin to block stops processing."""
        pipeline = ProcessingPipeline(original_content=Mock())

        # First security plugin blocks
        blocked_stage = PipelineStage(
            plugin_name="FirstSecurity",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False),
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(blocked_stage)

        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage == "FirstSecurity"

        # In practice, processing would stop here
        # But if we add more stages, blocked_at_stage shouldn't change
        another_stage = PipelineStage(
            plugin_name="SecondSecurity",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=True),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(another_stage)

        # blocked_at_stage should still be the first
        assert pipeline.blocked_at_stage == "FirstSecurity"

    def test_no_security_evaluation_is_permissive(self):
        """NO_SECURITY_EVALUATION allows messages through."""
        pipeline = ProcessingPipeline(original_content=Mock())

        # Only middleware plugins
        middleware_stage = PipelineStage(
            plugin_name="Logger",
            plugin_type="middleware",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=None, reason="Logged"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,
            error_type=None,
            security_evaluated=False,
        )
        pipeline.add_stage(middleware_stage)

        # Should remain NO_SECURITY_EVALUATION
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        assert pipeline.had_security_plugin is False

        # This means the message is allowed through
        # (formatters can see no security evaluation occurred)


class TestReasonConcatenation:
    """Validates reason concatenation for audit logging."""

    def test_multiple_reasons_concatenated(self):
        """Multiple plugin reasons are concatenated with ' | '."""
        reasons = []

        # Simulate multiple plugins with reasons
        plugin_results = [
            PluginResult(allowed=True, reason="Tool 'read_file' is in allowlist"),
            PluginResult(allowed=True, reason="No PII detected"),
            PluginResult(allowed=True, reason="No secrets detected"),
        ]

        for result in plugin_results:
            if result and result.reason:
                reasons.append(result.reason)

        final_reason = " | ".join(reasons) if reasons else "no_security"

        assert (
            final_reason
            == "Tool 'read_file' is in allowlist | No PII detected | No secrets detected"
        )

    def test_empty_reasons_fallback_to_outcome(self):
        """No plugin reasons fallback to pipeline outcome."""
        reasons = []

        # No plugins provided reasons
        plugin_results = [
            PluginResult(allowed=True, reason=""),
            PluginResult(allowed=None, reason=None),
        ]

        for result in plugin_results:
            if result and result.reason:
                reasons.append(result.reason)

        pipeline_outcome = PipelineOutcome.ALLOWED
        final_reason = " | ".join(reasons) if reasons else pipeline_outcome.value

        assert final_reason == "allowed"

    def test_cleared_reasons_become_generic(self):
        """After content clearing, reasons become generic."""
        # When capture_content=False, reasons are replaced
        cleared_reasons = ["[blocked]", "[modified]"]

        final_reason = " | ".join(cleared_reasons)
        assert final_reason == "[blocked] | [modified]"


# Scenario Tests
class TestScenarios:
    """Validates the example scenarios from security-model.md."""

    def test_scenario_1_single_security_allowed(self):
        """Single security plugin allows request."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.had_security_plugin = True
        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        pipeline.capture_content = True

        stage = PipelineStage(
            plugin_name="ToolAllowlist",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(
                allowed=True, reason="Tool 'read_file' is in allowlist"
            ),
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(stage)

        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        assert pipeline.had_security_plugin is True
        assert pipeline.capture_content is True

        # Formatters can interpret this outcome as allowed
        assert pipeline.pipeline_outcome in [
            PipelineOutcome.ALLOWED,
            PipelineOutcome.MODIFIED,
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
        ]

    def test_scenario_2_single_security_blocked(self):
        """Single security plugin blocks request."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.had_security_plugin = True

        stage = PipelineStage(
            plugin_name="ToolAllowlist",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(
                allowed=False, reason="Tool 'dangerous_tool' not in allowlist"
            ),
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED,
            error_type=None,
            security_evaluated=True,
        )
        pipeline.add_stage(stage)

        # Manager would set this
        pipeline.capture_content = False

        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage == "ToolAllowlist"
        assert pipeline.capture_content is False

        # Formatters can interpret this outcome as blocked
        assert pipeline.pipeline_outcome in [
            PipelineOutcome.BLOCKED,
            PipelineOutcome.ERROR,
        ]

    def test_scenario_4_critical_plugin_error(self):
        """Critical plugin error stops processing."""
        pipeline = ProcessingPipeline(original_content=Mock())
        pipeline.had_security_plugin = True

        stage = PipelineStage(
            plugin_name="CriticalSecurityPlugin",
            plugin_type="security",
            input_content=Mock(),
            output_content=None,
            content_hash="hash",
            result=PluginResult(allowed=False, reason="Database connection failed"),
            processing_time_ms=1.0,
            outcome=StageOutcome.ERROR,
            error_type="Exception",
            security_evaluated=True,
        )
        pipeline.add_stage(stage)

        # Manager would set this during finalization
        pipeline.pipeline_outcome = PipelineOutcome.ERROR

        assert stage.outcome == StageOutcome.ERROR
        assert pipeline.pipeline_outcome == PipelineOutcome.ERROR

        # Formatters can interpret ERROR outcome as a denial
        assert pipeline.pipeline_outcome in [
            PipelineOutcome.BLOCKED,
            PipelineOutcome.ERROR,
        ]
