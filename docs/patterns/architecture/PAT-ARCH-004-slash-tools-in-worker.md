---
id: PAT-ARCH-004
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Slash-command tools run in the inference worker; results are assistant replies

## Problem
Tools had three calling conventions and no caller in the message flow. `ToolService` turned
every failure into HTTP 200 text, held a global lock while a tool ran, and let client JSON
replace server objects in the tool context. Running tools in a transport would add a second
reply writer and an Ollama call outside the FIFO worker.

## Context
Applies to every module in `app/intelligence/tools/` and to every caller of
`ToolService.invoke` (the inference worker and `POST /api/v1/intel/tools/{name}/invoke`).
It builds on PAT-ARCH-001 (only the worker writes replies) and PAT-ARCH-003 (worker-built
prompts). Decided in [ADR-0004](../../adr/0004-slash-tools-in-worker.md). Its only dependency
on unapplied changes is the two amendments to accepted PAT-ARCH-003 flagged in ADR-0004:
slash-command jobs skip the chat builder (rule 5), and the worker's `chat` and the service's
`generate` share `_ollama_lock` (rule 6). It does not cover streaming (REQ-0007) or the gated
two-step narrate/adjudicate flow.

## Solution
1. **Tool contract.** A module exposes `NAME: str` and `run(args: str, context: dict)`, which
   returns `str` or `{"text": str, "meta": dict}`. A bad user input raises
   `app.intelligence.tools.ToolError`. Any other exception is a bug and propagates. Tools
   never write messages. Discovery is only via `discover_tool_modules` (ADR-0001).
   A module also exposes `DESCRIPTION: str`, one plain-language line shown in the client tool
   picker. `GET /api/v1/intel/tools` returns it as `description` ("" if absent).
2. **Context.** Server-owned keys are `inference`, `repos`, `store`, `session_id`,
   `message_id`, `logger`, `rng`. `session_id`/`message_id`/`store` are set only by the worker.
   Client context can add keys, never replace these. Dropped keys are logged by name at
   WARNING.
3. **Dispatch.** `submit_user_message` enqueues as usual. The worker calls
   `detect_tool(job.prompt)`. On a match it invokes the tool instead of building a chat
   request. On success it writes the result with `_append_reply` as
   `role='assistant'` and `meta = {**tool_meta, "reply_to", "tool": NAME}`, then marks the user
   message `completed`; replies also carry `meta.kind` (PAT-ARCH-013). On failure it marks the user message `error` with `meta.error`. No new
   role or status.
4. **LLM access.** Tools call `context["inference"].generate(prompt)`. It and the worker's
   `client.chat` share one `_ollama_lock`, so Ollama calls never overlap.
5. **Errors.** `invoke` raises `UnknownToolError` or lets exceptions propagate, and takes the
   registry lock only for lookup. HTTP: 200 ok, 404 unknown, 400 `ToolError`, 502
   `IntelligenceError`, 500 other. The error message goes in `ToolInvokeResp.error`.
6. Tests stub `inference.generate` / `client.chat`, inject `rng`, and use
   `SqliteSessionStore(":memory:")`.

## Consequences
- One reply writer and one dispatch path for REST and WS. Tools are testable as pure
  functions.
- Tools queue behind LLM jobs. Tool exchanges appear in LLM history and in the snapshot.
- Unknown `/x` is an error, not plain chat.
- There is no `clear` tool. `app/intelligence/tools/clear.py` is deleted by human decision
  (2026-10-11, debug shorthand), so `/clear` is an unknown tool and gets the normal
  unknown-tool error (worker: user message `error`; `/invoke`: HTTP 404).

## Examples
None yet. Planned: `app/services/inference_service.py` `_worker_loop`,
`app/services/tool_service.py` `invoke`, `app/intelligence/tools/{roll,narrate}.py`
(REQ-0008). `app/intelligence/tools/clear.py` is deleted.
