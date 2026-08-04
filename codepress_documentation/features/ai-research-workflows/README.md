---
feature: ai-research-workflows
area: backend/ai
created: 2026-08-04
last_updated: 2026-08-04
---

# AI Research Workflows

## Overview

The AI domain helps researchers and editors identify experts, prepare outreach, draft proposals, summarize funding calls, and review proposals. It is split between general research-assistance workflows (`research_ai`) and structured proposal-review workflows (`ai_peer_review`).

## Architecture

`research_ai` persists expert searches, experts, generated emails, templates, proposal drafts, and agent conversations/executions. Its API supports search creation/progress, expert management, email generation/preview/send, RFP applicant outreach, and proposal drafts. The agent layer uses provider adapters selected through a registry; `AgentService` assembles an agent from an injected provider, tools, prompts, execution limits, and an optional recorder.

`ai_peer_review` persists proposal reviews, RFP summaries, editorial feedback, and key insights. Its services wrap prompts and LLM providers while its views expose grant-scoped review and summary endpoints. Existing scoring rules are described in `docs/PROPOSAL_REVIEW_SCORING.md`.

## Key Files

- `src/research_ai/urls.py` — expert finder, outreach, templates, and proposal-draft routes.
- `src/research_ai/models/agent.py` — conversation, context, execution, and message records.
- `src/research_ai/models/expert_search.py`, `expert.py`, and `generated_email.py` — expert discovery and outreach data.
- `src/research_ai/services/agent/agent_service.py` — explicit agent construction.
- `src/research_ai/services/agent/providers/` — provider abstraction and implementations.
- `src/research_ai/services/agent/tools.py` and `loop.py` — toolset and bounded agent execution.
- `src/ai_peer_review/models.py` — proposal reviews, summaries, feedback, and key-insight models.
- `src/ai_peer_review/services/` and `prompts/` — review orchestration and prompt assets.
- `src/ai_peer_review/urls.py` — proposal review, feedback, and RFP-summary APIs.

## Change Guidance

- Keep provider selection behind the provider registry and preserve explicit iteration/token limits in callers.
- Treat prompts as versioned product behavior: update tests and persisted output expectations when prompt semantics change.
- Do not blur generated draft/recommendation data with final human decisions, invitations, or publication state.
- Protect scoped resources: proposal, grant, unified-document, and editor permissions must be checked before generation or retrieval.

## Keywords

AI, LLM, agent, provider, Bedrock, Claude, OpenRouter, expert finder, outreach, generated email, proposal draft, peer review, RFP, editorial feedback, prompts
