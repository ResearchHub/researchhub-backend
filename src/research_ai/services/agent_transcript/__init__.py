"""Django-side persistence of agent-core conversations.

The agent core (``research_ai.services.agent``) stays Django-free; this package
is the injected implementation side: ``DatabaseAgentRecorder`` satisfies the
core's ``AgentRecorder`` protocol and writes the transcript incrementally, and
``build_context`` is the single seam that turns a stored transcript back into
the message list a run resumes from.
"""

from research_ai.services.agent_transcript.context import build_context
from research_ai.services.agent_transcript.recorder import DatabaseAgentRecorder

__all__ = ["DatabaseAgentRecorder", "build_context"]
