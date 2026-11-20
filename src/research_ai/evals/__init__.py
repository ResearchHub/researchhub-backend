"""Offline evals for the assistant and notebook chat agents.

A case (``cases/<agent>/*.yaml``) seeds a user and, for the notebook agent, a
note; ``harness`` drives its scripted user turns through the production chat
engine with a real model; ``scorers`` grade the persisted trace and the notes
the run left behind; ``report`` writes the results. ``run_agent_evals`` is
the entry point. Runs commit real rows, so point it at a throwaway stack.
"""
