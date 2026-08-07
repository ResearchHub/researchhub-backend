"""The ambient liveness reporter provider calls touch."""

from types import SimpleNamespace
from unittest import TestCase

from django.test import SimpleTestCase

from research_ai.services.agent import heartbeat
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.openrouter import OpenRouterProvider


class AgentHeartbeatTests(TestCase):
    def test_a_touch_reaches_the_installed_reporter(self):
        # Arrange
        touched = []

        # Act
        with heartbeat.reporting_to(lambda: touched.append("alive")):
            heartbeat.touch()

        # Assert
        self.assertEqual(touched, ["alive"])

    def test_a_touch_outside_any_run_does_nothing(self):
        # Act & Assert: most callers of a provider are not being tracked at all,
        # so no reporter is the ordinary case rather than a misconfiguration.
        heartbeat.touch()

    def test_the_reporter_does_not_outlive_its_run(self):
        # Arrange
        touched = []

        # Act
        with heartbeat.reporting_to(lambda: touched.append("alive")):
            pass
        heartbeat.touch()

        # Assert: a later call must not report a finished run alive.
        self.assertEqual(touched, [])

    def test_a_nested_run_reports_to_itself_then_restores_the_outer_one(self):
        # Arrange: an agent run started from inside another run's tool handler.
        touched = []

        # Act
        with heartbeat.reporting_to(lambda: touched.append("outer")):
            with heartbeat.reporting_to(lambda: touched.append("inner")):
                heartbeat.touch()
            heartbeat.touch()

        # Assert
        self.assertEqual(touched, ["inner", "outer"])

    def test_a_reporter_that_raises_does_not_break_the_provider_call(self):
        # Arrange: reporting is an observation of the run, not part of it.
        def _broken():
            raise RuntimeError("database hiccup")

        # Act & Assert
        with heartbeat.reporting_to(_broken):
            heartbeat.touch()


def _boom(**_kwargs):
    raise RuntimeError("no network in tests")


class _ExplodingClient:
    """Every adapter's call surface at once, all of it refusing to run.

    The response never matters here: what is under test is that the touch
    happens *before* the adapter goes to work, so the call only has to reach the
    client and fail.
    """

    converse = staticmethod(_boom)
    messages = SimpleNamespace(create=_boom)
    chat = SimpleNamespace(completions=SimpleNamespace(create=_boom))


class ProviderLivenessContractTests(SimpleTestCase):
    """Every adapter reports before calling out (see ``providers.base``).

    A provider call is the unit of legitimate silence, so an adapter that skips
    this makes a run waiting on it -- including one inside a tool handler that
    judges or scores with provider calls of its own -- look abandoned for the
    call's whole duration. A new adapter belongs in this list.
    """

    def _touches(self, provider) -> int:
        touched = []
        with (
            heartbeat.reporting_to(lambda: touched.append("alive")),
            self.assertRaises(Exception),
        ):
            provider.complete(
                system_prompt="you are a test",
                messages=[],
                rendered_tools={},
                max_tokens=16,
                temperature=0.0,
            )
        return len(touched)

    def test_bedrock_reports_before_calling_out(self):
        # Arrange / Act / Assert
        provider = BedrockProvider(client=_ExplodingClient(), model_id="test-model")
        self.assertEqual(self._touches(provider), 1)

    def test_claude_platform_reports_before_calling_out(self):
        # Arrange / Act / Assert
        provider = ClaudePlatformProvider(
            client=_ExplodingClient(), model_id="test-model"
        )
        self.assertEqual(self._touches(provider), 1)

    def test_openrouter_reports_before_calling_out(self):
        # Arrange / Act / Assert
        provider = OpenRouterProvider(client=_ExplodingClient(), model_id="test-model")
        self.assertEqual(self._touches(provider), 1)
