# Claude Agent SDK Backend (Subscription Auth) — Spike Spec

**Date:** 2026-06-16
**Milestone:** Plan 8 (spike)
**Status:** Built + validated live (this spec documents the spike outcome)

## 1. Goal

Let the tool run LLM calls on a user's **Claude Pro/Max subscription** via the **Claude
Agent SDK** instead of per-token API credits. The tool is local-first and open-source, so
each user can bring their own Claude plan (the SDK's supported "your own projects" /
"third-party apps that authenticate with your Claude subscription" case). Practical driver:
live dogfooding drained API credits; the web-search fan-out is credit-hungry.

## 2. Verified facts (from the live spike)

- `pip install claude-agent-sdk` (v0.2.103); `query(prompt, options=ClaudeAgentOptions(...))`
  is an async generator; the final `ResultMessage.result` carries the text.
- **Subscription auth works** when `ANTHROPIC_API_KEY` is *absent from the process env* — the
  SDK then uses the logged-in `claude` CLI session (the Max plan). Proven: a completion
  returned cleanly with the key stripped.
- **The `env` option cannot remove an inherited key.** The subprocess inherits `os.environ`;
  passing `env=` without the key still leaks it (→ "Invalid API key"), and `env={"…KEY":""}`
  hangs the CLI on an auth prompt. So the key must be genuinely absent from `os.environ` at
  spawn time.
- `setting_sources=[]` isolates the call from the project's `CLAUDE.md`/skills (avoids leaking
  them into prompts and trims context overhead).
- Cost shape: each call spawns the Claude Code engine (subprocess) with ~18k cached context
  tokens of overhead and ~6s+ startup — **much slower than the raw Messages API** (a live
  assess took ~23s for rubric+grade vs ~4s on the API path).

## 3. Locked decisions

- **§3.1 Env-gated, opt-in, non-breaking.** `AA_LLM_BACKEND=agent_sdk` selects the SDK
  backend; default (unset) keeps the API-key client. Nothing changes unless you opt in.
- **§3.2 Behind the existing Protocol seam.** `AgentSDKLLMClient` implements the `LLMClient`
  Protocol (`complete(system, messages, tools) -> LLMResponse`) — a drop-in for
  `AnthropicLLMClient`. Engine and routes are untouched. `get_anchor_client` also uses it in
  agent_sdk mode (anchors are a no-tools structured call) by injecting it into the
  transport-agnostic `AnthropicAnchorClient(llm=…)`.
- **§3.3 Subscription auth via per-call key strip.** `complete()` pops `ANTHROPIC_API_KEY`
  from `os.environ` for the duration of the call (under a lock) and restores it after, so the
  subprocess uses the subscription while the still-API-key Researcher/Anchor clients (which
  capture their key at construction) keep working.
- **§3.4 Single-turn structured calls only.** `ClaudeAgentOptions(max_turns=1, allowed_tools=[],
  setting_sources=[])`; messages flattened to one prompt. `complete()` bridges **tool-use
  turns** (the Tutor's gated `reveal_solution`) to the API-key client so the Tutor stays
  functional — tool-use is not ported to the SDK yet.
- **§3.5 Async→sync bridge** via `asyncio.run` inside the sync `complete()` (FastAPI sync
  routes run in a threadpool worker with no running loop).

## 4. Known limitations (spike; follow-ups)

- **Latency/overhead:** ~6s+ per call vs ~sub-second on the API; agent_sdk mode is noticeably
  slower. Fine for personal dogfooding, not for latency-sensitive use.
- **Serialization:** the key-strip lock serializes concurrent `AgentSDKLLMClient.complete()`
  calls, so anchor fan-out runs sequentially in agent_sdk mode.
- **Race window:** while the key is popped, a *concurrently constructed* API-key client
  (e.g. a research request's `get_researcher`) would `KeyError`. Narrow (single-user,
  research and tutoring rarely overlap) but real. The clean fix is to also route the
  Researcher through the SDK (so the key can be dropped process-wide) — a follow-up.
- **Not ported:** web-search fan-out (Researcher) — needs the SDK's `WebSearch` tool; and
  native tool-use (Tutor reveal_solution) — currently bridged to the API key. A
  pure-subscription user with **no key set** gets a legible `AgentSDKError` → 502 on Tutor
  tool-turns (not a 500), telling them to set a key or use assess/curriculum/anchors.
- **Error legibility:** `AgentSDKError` (auth/usage/subscription failures) is registered with
  the app's exception handlers → **502**, matching the API-key backend's legible-error contract.
- **ToS:** personal / your-own-subscription use is the supported case; *hosting* a service
  that brokers other users' claude.ai logins needs API keys/approval. Open-source BYO-plan
  local use is fine.

## 5. Definition of done (met)

- `AgentSDKLLMClient` behind the `LLMClient` Protocol, selected by `AA_LLM_BACKEND=agent_sdk`,
  default unchanged. Unit-tested (flatten, key strip+restore, error result, tool-use bridge).
- A **live assess ran end-to-end on the subscription** (key stripped, `200`, real anchored
  grade) — proven, plus the gate returns `AgentSDKLLMClient` with the flag on and the API-key
  client with it off.
- Full suite green, ruff clean; the new dependency added to `pyproject`.

## 6. Out of scope (follow-ups)

Researcher web-search via the SDK's `WebSearch` tool (the original "Agent SDK for fan-out"
plan); native Tutor tool-use on the SDK; eliminating the key-strip race by going
subscription-only process-wide; latency optimization (persistent SDK session / `ClaudeSDKClient`).
