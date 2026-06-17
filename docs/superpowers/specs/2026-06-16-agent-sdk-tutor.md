# Agent SDK Tutor (Subscription) — Spec

**Date:** 2026-06-16
**Milestone:** Plan 10 (completes subscription mode)
**Status:** Approved (focused; user-directed "port the Tutor tool-use to the SDK")

## 1. Goal

Make the generation-first **Tutor work in `agent_sdk` mode (subscription, no API key)**. The
Tutor is the only feature left on the API-key path because its attempt-gate uses raw-API
tool-use, which the Agent SDK (autonomous tool execution) doesn't expose. Port it so
`agent_sdk` mode is complete: research/assess/curriculum/anchors/remediation **and** tutoring
all on the Claude plan.

## 2. Verified facts (spike)

- The SDK runs in-process tools via `tool()` + `create_sdk_mcp_server()`; tool names are
  namespaced `mcp__<server>__<tool>`.
- The `can_use_tool` permission callback requires **streaming-input mode** (an async-iterable
  prompt), so it's not used. Instead the **attempt-gate lives inside the `reveal_solution`
  tool handler** (returns a BLOCKED, `is_error` result when no attempt is logged) — keeping
  the gate **code-enforced**, exactly like the existing `_execute_tool`.
- Validated live on the subscription: asked for an answer with no attempt → the model called
  `reveal_solution` → handler blocked it → the model gave one hint, solution NOT revealed.

## 3. Locked decisions

- **§3.1 Shared gate.** Extract `reveal_gate(attempt_logged) -> (allowed, message)` into
  `engine/tools.py` as the single source of truth for the attempt-gate; both the existing
  raw-API `_execute_tool` and the new SDK tutor use it.
- **§3.2 New `engine/tutor_sdk.py`: `run_tutor_turn_sdk(session, convo, user_text)`** runs the
  whole turn as ONE SDK `query()` with two in-process tools (`log_attempt`, `reveal_solution`)
  defined as closures over the conversation, `permission_mode="bypassPermissions"` (only those
  two tools are exposed), `setting_sources=[]`, and the existing tutor system prompt. The
  conversation history is flattened into the prompt (the SDK query is stateless). The reply is
  `ResultMessage.result`. Same `TurnResult` shape; same event kinds (`levels`, `tool:log_attempt`,
  `tool:reveal_solution:allowed|blocked`); `is_error` result → `AgentSDKError` → 502.
- **§3.3 Route selection.** `send_message` calls `run_tutor_turn_sdk` when
  `use_agent_sdk()` (renamed public in deps), else the existing `run_tutor_turn`. The API path
  is byte-for-byte unchanged. The unused `llm` dependency stays (harmless).
- **§3.4 Behavioural deltas (accepted).** An *allowed* reveal is no longer verbatim-terminal —
  the model receives the solution tool result and writes the final reply (natural-language,
  arguably better). The gate enforcement (block before attempt) is identical.

## 4. Known limitations / follow-ups

- **Latency:** the SDK agent loop (~subprocess cold-start) makes each tutor turn slower than
  the API path. Acceptable for personal use.
- **History via prompt-flatten** (not SDK sessions): the whole conversation is re-sent each
  turn (same as the API path re-sending `messages`). Fine for now; SDK session resume is a
  possible optimization.

## 5. Definition of done

- `agent_sdk` mode tutoring works end-to-end on the subscription with the attempt-gate
  enforced (verified live: blocked-before-attempt, allowed-after).
- `reveal_gate` is shared + unit-tested; the API tutor path is unchanged and its tests pass;
  `run_tutor_turn_sdk` orchestration (persist user+reply, emit events, return reply) is tested
  with a mocked `query`.
- Full suite green, ruff clean. With this, **agent_sdk mode is fully subscription-only and
  feature-complete** (no API key required for any feature).

## 6. Out of scope

SDK session-based history; latency optimization; a hybrid subscription+key mode.
