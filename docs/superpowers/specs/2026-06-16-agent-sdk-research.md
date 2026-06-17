# Agent SDK Researcher + Fully-Subscription Mode — Spec

**Date:** 2026-06-16
**Milestone:** Plan 9 (follow-up to the Agent SDK spike, Plan 8)
**Status:** Approved (focused; user-directed "port research to the SDK, make agent_sdk mode key-free")

## 1. Goal

Port the Researcher's web-search fan-out to the Agent SDK's built-in **`WebSearch`** tool so
it runs on the user's Claude **subscription**, and make `agent_sdk` mode **fully
subscription-only — no `ANTHROPIC_API_KEY` required**. This (a) moves the credit-hungry
web-search onto the plan, (b) lets us **drop the API key process-wide**, which **deletes the
per-call key-strip lock + race** from the spike, and (c) makes the open-source BYO-plan
experience key-free.

## 2. Verified facts (live)

- SDK `WebSearch` returns real sources on the subscription, parsed by the **existing**
  `parse_sources_json` (10 sources w/ tiers + relevance from one angle). The required option
  is `permission_mode="bypassPermissions"` — without it WebSearch waits on an approval prompt
  and hangs. Safe here because `allowed_tools=["WebSearch"]` is the only tool exposed.
- Cost shape: ~60–115s per angle (subprocess cold-start ~30s + several searches). Fan-out runs
  the angles in parallel (existing `ThreadPoolExecutor`), so wall-clock ≈ the slowest angle.

## 3. Locked decisions

- **§3.1 `AgentSDKResearcherClient`** implements the `ResearcherClient` Protocol
  (`search(brief) -> list[RawSource]`) via `query(prompt=brief.query, options=...WebSearch,
  bypassPermissions, setting_sources=[], system_prompt=<reuse the API researcher's prompt>)`,
  parsing the result with the existing `parse_sources_json` and stamping the brief's angle.
  Drop-in behind the seam; the `research_topic` orchestrator is untouched.
- **§3.2 Fully subscription-only in agent_sdk mode.** `create_app()` pops
  `ANTHROPIC_API_KEY` from `os.environ` **once** when `AA_LLM_BACKEND=agent_sdk`, so every
  subprocess (LLM, researcher, anchors) uses the subscription. No client in that mode needs
  the key (verified: `get_llm`/`get_researcher`/`get_anchor_client` all return SDK-backed
  clients).
- **§3.3 Delete the key-strip lock.** Because the key is gone process-wide,
  `AgentSDKLLMClient` no longer pops/restores it per call — it just `query()`s. This
  **removes the lock and the race** from Plan 8 and makes anchor fan-out / concurrent LLM
  calls genuinely parallel.
- **§3.4 Tutor tool-use** (reveal_solution) is still not ported; in agent_sdk mode (no key) a
  tutor turn raises a legible `AgentSDKError` → 502 directing the user to set a key or use the
  other features. Porting tutor tool-use to an SDK custom tool is the next follow-up.
- **§3.5 `get_researcher`** returns `AgentSDKResearcherClient` in agent_sdk mode, else the
  API-key client (unchanged default).

## 4. Known limitations / follow-ups

- **Latency:** SDK web-search is much slower than the server-side `web_search` API tool
  (~minutes for a fan-out vs ~75s). Acceptable for personal/dogfood use.
- **Tutor:** generation-first tutoring's gated reveal_solution needs a tool-use port to work
  in pure-subscription mode (next milestone). Until then, agent_sdk mode = everything except
  the Tutor's reveal gate; default (API-key) mode is unchanged and full-featured.
- **5 concurrent subprocesses:** the fan-out spawns up to 5 `claude` engines at once (heavier
  than API calls). Fine on a dev machine; `max_workers` can be tuned later.

## 5. Definition of done

- `AgentSDKResearcherClient` behind the Protocol, gated by `AA_LLM_BACKEND=agent_sdk`,
  parsing via the existing parser; unit-tested (parse + angle stamp + is_error → AgentSDKError).
- `create_app()` drops the key in agent_sdk mode (unit-tested); the per-call key-strip
  lock/pop is removed from `AgentSDKLLMClient`.
- A **live research fan-out runs on the subscription with no API key set** and returns
  sources end-to-end.
- Full suite green, ruff clean; default (API-key) mode fully unchanged.

## 6. Out of scope

Tutor tool-use port (next); latency optimization (persistent `ClaudeSDKClient` session,
caching cold-starts); a hybrid "subscription generation + API-key tutor" mode.
