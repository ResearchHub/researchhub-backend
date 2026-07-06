"""Unit tests for the optional LLM Observability wrapper (no ddtrace required)."""

from unittest import mock

from django.test import SimpleTestCase

from research_ai.services.agent import observability


class EnableLLMObservabilityTests(SimpleTestCase):
    def setUp(self):
        # Arrange: every test starts from the disabled module state.
        self._reset = mock.patch.object(observability, "_enabled", False)
        self._reset.start()
        self.addCleanup(self._reset.stop)

    def test_disabled_when_env_flag_unset(self):
        # Arrange: a real LLMObs is present but the opt-in flag is missing.
        with (
            mock.patch.object(observability, "LLMObs", mock.Mock()) as llmobs,
            mock.patch.dict("os.environ", {}, clear=True),
        ):
            # Act
            active = observability.enable_llm_observability()

        # Assert: stays off and never touches the SDK.
        self.assertFalse(active)
        llmobs.enable.assert_not_called()

    def test_disabled_when_ddtrace_missing(self):
        # Arrange: ddtrace import failed -> LLMObs is None, flag is on.
        with (
            mock.patch.object(observability, "LLMObs", None),
            mock.patch.dict("os.environ", {"DD_LLMOBS_ENABLED": "1"}, clear=True),
        ):
            # Act / Assert
            self.assertFalse(observability.enable_llm_observability())

    def test_enables_when_flag_set(self):
        # Arrange
        llmobs = mock.Mock()
        with (
            mock.patch.object(observability, "LLMObs", llmobs),
            mock.patch.dict("os.environ", {"DD_LLMOBS_ENABLED": "true"}, clear=True),
        ):
            # Act
            active = observability.enable_llm_observability()

        # Assert
        self.assertTrue(active)
        llmobs.enable.assert_called_once()

    def test_enable_failure_is_swallowed(self):
        # Arrange: SDK enable raises -> we report inactive, not crash.
        llmobs = mock.Mock()
        llmobs.enable.side_effect = RuntimeError("boom")
        with (
            mock.patch.object(observability, "LLMObs", llmobs),
            mock.patch.dict("os.environ", {"DD_LLMOBS_ENABLED": "1"}, clear=True),
        ):
            # Act / Assert
            self.assertFalse(observability.enable_llm_observability())


class SpanHelpersTests(SimpleTestCase):
    def test_spans_are_noops_when_inactive(self):
        # Arrange: disabled module state.
        with mock.patch.object(observability, "_enabled", False):
            # Act
            with observability.agent_span("a") as a, observability.tool_span("t") as t:
                observability.annotate(a, input_data="x")  # must not raise

            # Assert: no span object handed out when inactive.
            self.assertIsNone(a)
            self.assertIsNone(t)

    def test_spans_delegate_when_active(self):
        # Arrange: active module state with a fake SDK.
        llmobs = mock.MagicMock()
        with (
            mock.patch.object(observability, "_enabled", True),
            mock.patch.object(observability, "LLMObs", llmobs),
        ):
            # Act
            with observability.agent_span("agent_x") as span:
                observability.annotate(span, input_data="in", output_data="out")

        # Assert: delegates to the SDK with our name and annotation.
        llmobs.agent.assert_called_once_with(name="agent_x")
        llmobs.annotate.assert_called_once()
        _, kwargs = llmobs.annotate.call_args
        self.assertEqual(kwargs["input_data"], "in")
        self.assertEqual(kwargs["output_data"], "out")

    def test_annotate_swallows_sdk_errors(self):
        # Arrange: active, but the SDK annotate raises.
        llmobs = mock.MagicMock()
        llmobs.annotate.side_effect = RuntimeError("boom")
        with (
            mock.patch.object(observability, "_enabled", True),
            mock.patch.object(observability, "LLMObs", llmobs),
        ):
            # Act / Assert: telemetry failure must not propagate.
            observability.annotate(mock.Mock(), input_data="x")
