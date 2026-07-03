"""Headless proposal-drafting run.

- ``runner`` -- the bounded-loop driver and the ``run_proposal_draft`` entry
  point (see its module docstring for the design overview).
- ``gates`` -- the deterministic accept/reject checks a submit must clear.
- ``config`` -- the settings-backed knobs for one run.
- ``note_writer`` -- persists the accepted proposal as a ``Note``.
"""

from research_ai.services.proposal_draft.runner import run_proposal_draft

__all__ = ["run_proposal_draft"]
