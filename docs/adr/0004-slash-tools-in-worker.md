---
id: ADR-0004
status: accepted
date: 2026-10-11
requirement: REQ-0008
supersedes: null
superseded_by: null
---

# Slash-command tools run in the inference worker; results are assistant replies

## Context
REQ-0008 ([LOG](../requirements/LOG.md)) requires `narrate` and `roll` to work end to end,
`clear` to be deleted (human decision 2026-10-11), slash commands to be dispatched in the
message flow shared by REST and WS, and `ToolService` to stop swallowing errors, holding a
global lock during runs, and letting client context override service objects.

Verified against the tree on 2026-10-11:
- `narrate.py` treats `args` as a dict, calls `build_narrator_prompt(game=, session_run=, ...)`
  (current signature is `(adjudicator_output: str, params: NarratorVoiceParams, player_intent=None)`)
  and `inference.generate(prompt)`. `OllamaInferenceService` has no `generate`, only `self.client`.
- `roll.py` is a stub (`run_roll_tool`). `clear.py` uses `session_run.entries.clear()` and
  `session.commit()`. Neither exposes `NAME`/`run`, so neither is discovered.
- `ToolService.invoke` holds `self._lock` (RLock) for the whole tool run. It returns
  `"Unknown tool: x"` and `"Tool x error: e"` as plain values. It merges caller context over
  `default_context`. `invoke_tool` in `app/api/v1/intelligence.py` then returns 200 with `error=None`.
- `tool_handler.detect_tool` (regex `^/([^\s/]+)(?:\s+(.*))?$`) has no caller.
- REST `post_message` and WS `_handle_user_message` both call `submit_user_message`, which
  enqueues `prompt=content`. Only the worker writes replies (`_append_reply`, role `assistant`,
  `meta.reply_to`). WS `_find_reply` matches only `role == "assistant"`. `post_message`
  answers 429 whenever `submit_user_message` reports `queued=False`.
- `build_chat_messages` keeps completed `user`/`assistant` messages before the current one.
  `MessageCreateReq` lets a client set `role` and `meta`.
- Every live Ollama call goes through the single worker thread today
  (`generate_tokens` is not reached by `ws.py`).

Patterns consulted: PAT-ARCH-001, PAT-ARCH-002, PAT-ARCH-003, PAT-CODE-001 (all accepted).

ADR triggers that fired: a cross-cutting error-handling convention changes (the ToolService
error contract and its HTTP mapping); the decision amends accepted PAT-ARCH-003 (worker job
shape, Ollama serialization); and there are two or more viable approaches for dispatch and
narrate's LLM access.

## Decision Drivers
| Dimension | Weight | Why it matters here |
|---|---|---|
| Simplicity / smallest-edit fit | High (3) | constraints.md 1 |
| Reversibility | High (3) | Tool output is persisted in SQLite; new roles or stored shapes are hard to undo |
| Maintainability for one part-time person | High (3) | Two reply writers or two dispatch paths would drift (the PAT-ARCH-001 history) |
| Reuse of existing patterns/dependencies | Medium (2) | `detect_tool`, `_append_reply`, `generate` exist already |
| Fun / learning value | Medium (2) | constraints.md 5; dice in chat is the fun part |
| Performance / scalability | Low (1) | One household; tools may queue behind narration |
| Security hardening beyond sane defaults | Low (1) | Only "client cannot replace service objects" is required |
| Accepted-contract fit (requirement-specific) | High (3) | REQ-0008 explicitly forbids changing REQ-0003/0006/0010 behaviour; PAT-ARCH-001 rule 4 and PAT-ARCH-003 FIFO are accepted |

Scores are 1 (poor) to 5 (strong). Weighted total = sum of (score x weight). Maximum 90.

## Considered Options and Rubric Scoring

### D1 - Where slash commands are dispatched, and how results are stored
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | Fit (3) | Total |
|---|---|---|---|---|---|---|---|---|---|
| D1-A Inline in `submit_user_message`, assistant reply | 2: `post_message` maps `queued=False` to 429, so REST and WS must both change | 4: code only | 2: a second reply writer; narrate's Ollama call blocks the `async def post_message` event loop | 3: reuses `detect_tool`, duplicates `_append_reply` | 3 | 1: Ollama call off the queue, concurrent with the worker | 3 | 1: breaks PAT-ARCH-001 rule 4 and FIFO | **43** |
| **D1-B Branch in `_worker_loop`, assistant reply with `meta.tool`** | 4: one branch plus a constructor arg; REST/WS/messages.py untouched | 5: delete the branch; no schema or role change | 5: one writer, one path; `_find_reply` works as is | 5: `detect_tool`, `_append_reply`, `_update_message_status`, `ToolService` | 4 | 3: `/roll` waits behind queued jobs | 3 | 5: keeps PAT-ARCH-001 rule 4, FIFO, REQ-0003 | **81** |
| D1-C Branch in worker, new `role='tool'` message | 3: also edit `_find_reply` and the history filter | 3: `tool` rows persist; frontend must learn the role | 3: new role vocabulary in WS, snapshot, history | 3: Ollama's `tool` role means function-call results, a semantic mismatch | 3 | 3 | 3 | 2: changes the REQ-0003 reply shape and the frontend contract (REQ-0010) | **51** |
| D1-D Status quo (no dispatch) | 5 | 5 | 2: `detect_tool` stays dead | 1 | 1 | 3 | 3 | 1: fails REQ-0008 (4) MUST | **49** |

### D2 - How narrate reaches the LLM
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | Fit (3) | Total |
|---|---|---|---|---|---|---|---|---|---|
| D2-A `context["inference"].client.chat(...)` directly | 5: no service change | 5 | 3: reaches into the service's client | 4 | 3 | 3 | 3 | 2: via `POST /intel/tools/narrate/invoke` (threadpool) it runs concurrently with the worker and breaks Ollama serialization | **65** |
| **D2-B `OllamaInferenceService.generate(prompt)` under one `_ollama_lock`, worker's `client.chat` under the same lock** | 4: about 8 lines; narrate's existing `inference.generate(prompt)` call stays | 5 | 4: one lock, two call sites (worker, narrate), so not speculative | 5: `OllamaClient.generate` is PAT-ARCH-003 rule 6's "kept for tools" wrapper | 3 | 3: `/invoke` may wait for one job | 3 | 4: Ollama calls never overlap; queue stays FIFO; Protocols unchanged; lock is not FIFO across worker and `/invoke` | **73** |
| D2-C Sessionless job kind on the worker queue plus a Future for `/invoke` | 2: new job type and Future plumbing | 3 | 3 | 3 | 4 | 3 | 3 | 5: strict FIFO | **59** |

### D3 - ToolService error contract
| Option | Simp (3) | Rev (3) | Maint (3) | Reuse (2) | Fun (2) | Perf (1) | Sec (1) | Fit (3) | Total |
|---|---|---|---|---|---|---|---|---|---|
| **D3-A `invoke` raises typed errors (`UnknownToolError`, `ToolError`, others propagate); each caller maps them** | 4 | 5 | 5: impossible to forget an error, which was the original bug | 4: `IntelligenceError` already exists | 3 | 3 | 3 | 4: matches PAT-ARCH-001 rule 6 "fail loudly" | **74** |
| D3-B `invoke` never raises; returns `{text, meta, error, kind}` | 4 | 5 | 3: every caller must check `error`; stringly typed kinds | 3 | 2 | 3 | 3 | 3 | **61** |

### D4 - Fate of `clear` (human decision, not rubric-scored)
Decided by the human on 2026-10-11: `clear` was a debug shorthand, so it is deleted and not
ported. No options are scored.

## Decision Outcome
Choose **D1-B + D2-B + D3-A**, plus D4 (human decision). Each scored option won its table on the
weighted rubric (81, 73, 74).

1. **Dispatch.** `OllamaInferenceService.__init__(settings, tool_service=None)`. In `_worker_loop`,
   after marking the job `running`, `name, args = detect_tool(job.prompt)` when a tool service is
   wired. A match calls `tool_service.invoke(name, args, {"store", "session_id", "message_id"})`
   and skips the chat builder. No match runs the existing chat path unchanged. With
   `tool_service=None` there is no dispatch (test helpers keep current behaviour).
   `build_services` builds `ToolService(default_context={"repos": repos})` first, then the
   inference service with `tool_service=`, then sets `default_context["inference"]`.
2. **Storage.** Success: `_append_reply(..., meta={**tool_meta, "reply_to": user_id, "tool": name})`.
   The reply is `role='assistant'`, `completed`, and the user message becomes `completed`.
   `UnknownToolError`/`ToolError`/other: the user message becomes `error` with `meta.error`,
   and no reply is written (existing vocabulary; WS already sends an `error` event). Slash
   messages and tool replies stay in chat history like any completed message.
3. **Narrate.** `run(args, context)`: empty args raises `ToolError("Usage: /narrate <what happens>")`.
   `params = NarratorVoiceParams(tone, dm_persona=persona, verbosity=verbosity_default,
   sensory_focus, consequence_level)` from `get_settings().prompts`.
   `prompt = build_narrator_prompt(args.strip(), params, None)`. Returns
   `{"text": context["inference"].generate(prompt), "meta": {"tool": "narrate"}}`. The prompt is
   not put in meta or logs.
4. **Roll** (stdlib `re` + `random` only). Case-insensitive, whitespace allowed between tokens:
   `expr := term (('+'|'-') term)*` ; `term := dice | INT | 'adv' | 'dis'` ;
   `dice := INT? 'd' INT (('kh'|'kl') INT)?` ; `INT := [0-9]{1,4}`. `adv` = `2d20kh1`,
   `dis` = `2d20kl1`; empty args = `1d20`. Bounds (else `ToolError`): args at most 64 chars,
   at most 10 terms, count 1..100 (default 1), sides 2..1000, total dice at most 100,
   `1 <= keep <= count`, constants 0..1000. Pure `evaluate(expr, rng) -> dict`. `run` uses
   `context.get("rng")` or a module-level `random.Random()`. Text example:
   `4d6kh3+2: [6, 4, 3, (1)] + 2 = 15`. Meta: `{"tool": "roll", "expression", "total",
   "terms": [{"sign", "count", "sides", "keep", "rolls", "kept", "value"} | {"sign",
   "constant", "value"}]}`.
5. **Clear deleted (D4).** By human decision on 2026-10-11 (debug shorthand),
   `app/intelligence/tools/clear.py` is deleted, not ported. `clear` is not registered or
   dispatchable, and nothing replaces it. `/clear` is therefore an unknown tool and gets the
   existing unknown-tool error. In the worker it takes item 2's `UnknownToolError` path: the
   user message becomes `error` and no reply is written. `POST /api/v1/intel/tools/clear/invoke`
   returns item 7's 404 `Unknown tool: clear`. `build_chat_messages` is unchanged.
6. **ToolService.** `invoke(name, args="", context=None, *, client_context=None) -> {"text": str,
   "meta": dict}`. It takes the lock only to read the registry, and runs the tool outside it.
   Merge order: client keys minus `SERVER_CONTEXT_KEYS` (`inference, repos, store, session_id,
   message_id, logger, rng`) and minus `default_context` keys, then `default_context`, then
   server `context`. Dropped key names are logged at WARNING (names only). A `str` result
   becomes `{"text": s, "meta": {}}`. Unknown name raises `UnknownToolError`; tool exceptions
   propagate. `ToolError(ValueError)` lives in `app/intelligence/tools/__init__.py` (avoids a
   tools -> service import cycle).
7. **HTTP mapping** in `invoke_tool` (models unchanged): success 200 with `error=None`;
   `UnknownToolError` 404 `{"detail": "Unknown tool: x"}`; `ToolError` 400; `IntelligenceError`
   502; other 500 with `logger.exception`. Each error status carries `ToolInvokeResp(error=msg)`.
   The endpoint passes `client_context=req.context`.

Traded away: strict FIFO between `/intel/tools/*/invoke` and worker jobs (D2-C). A distinct
storage role for tool output (D1-C); tool replies are told apart only by `meta.tool`.

## Consequences
- Positive: REST and WS get slash commands with no transport edit. Only the worker writes
  replies. No new dependency, Protocol method, role, status, or schema change, and no change to
  `build_chat_messages`.
- Negative: `/roll` waits behind queued narration. A direct `/invoke` narrate plus a queued
  job can, at worst, push a WS reply past `ollama.timeout_seconds + 10`. Unknown `/x` is an
  error, not passed to the LLM. Tool chatter enters LLM history. `/clear` no longer exists and
  returns the unknown-tool error.
- Follow-up: `tool_handler.get_registry`/`run_tool` remain dead (ADR-0001 follow-up).
  Planned modules: `app/intelligence/tools/{roll,narrate}.py`; `app/intelligence/tools/clear.py`
  is deleted.
- Open gates (defaults, not decided here): (a) the two-step narrate/adjudicate flow
  (`settings.prompts.enable_narration` / `enable_adjudication`) stays unread; (b) unknown `/x`
  is an error and is not sent to the LLM; (c) tool exchanges stay in LLM history like any
  completed message.

## Pattern Impact
- Creates: PAT-ARCH-004 (accepted 2026-10-11).
- Uses without change: PAT-ARCH-001, PAT-ARCH-002, PAT-CODE-001, ADR-0001 (tool contract
  `NAME` + `run(args: str, context: dict)` kept; return narrowed to `str | {"text", "meta"}`).
- **Changes to accepted PAT-ARCH-003, approved by the human 2026-10-11 and applied, two
  amendments:** (i) rule 5 gains "slash-command jobs skip the chat builder and run the tool";
  (ii) rule 6 gains "worker `chat` and the service's `generate` run under one `_ollama_lock`".
