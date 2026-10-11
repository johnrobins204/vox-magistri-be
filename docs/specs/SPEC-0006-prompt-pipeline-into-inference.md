---
id: SPEC-0006
requirement: REQ-0006
adr: null
status: draft
date: 2026-10-11
---

# Prompt Pipeline Into Inference: The Worker Sends a Built Chat Request, Not Raw User Text

## 1. Requirement
> The inference worker and OllamaClient path MUST send an Ollama chat request built from
> the prompt pipeline (not raw user text): one `system` message from the DM role plus
> voice settings (`settings.prompts.*` and the corrected voice config file, loaded
> robustly via get_logger), then at most `settings.app.max_turns` completed prior
> messages of the session (oldest first, fields truncated to
> `settings.app.max_field_len`), then the current user message last; prompt builders MUST
> accept dict messages (no ORM attributes); `OllamaClient` MUST accept a messages list
> while `generate(prompt)` keeps working for tools; `app/intelligence/prompts.py` MUST
> import from `app.intelligence.prompting`; REST and WS MUST share this path; the
> pipeline MUST work with no campaign context; tests MUST run without network or Ollama.
> Session ids, the SessionStore API, message schema, status vocabulary and REQ-0003
> semantics MUST NOT change; streaming (REQ-0007), tool fixes (REQ-0008), auth
> (REQ-0009), API schema (REQ-0010) and campaign domain (REQ-0015) MUST NOT be changed
> under this requirement. (REQ-0006)

Linked ADR: **none** (the architect decided no ADR is needed; one call site, smallest-edit
choice per `docs/constraints.md` 1 and 2).
Linked patterns: [PAT-ARCH-003](../patterns/architecture/PAT-ARCH-003-prompt-pipeline-in-worker.md)
(**accepted** by the human on 2026-10-11; applied by this spec),
[PAT-ARCH-001](../patterns/architecture/PAT-ARCH-001-session-store-single-api.md) (accepted, applied, NOT modified),
[PAT-ARCH-002](../patterns/architecture/PAT-ARCH-002-stdlib-sqlite-store.md) (accepted, NOT modified),
[PAT-CODE-001](../patterns/code/PAT-CODE-001-centralized-logging.md) (accepted, applied, NOT modified).

### Decisions this spec implements (from the architect, Stage 3)
- **Build at run time in the worker.** Inside the existing `try` of
  `OllamaInferenceService._worker_loop`: `history = job.store.list_messages(job.session_id)`,
  then `build_chat_messages(...)`, then `self.client.chat(messages)`. Not at enqueue time
  (an enqueue-time build would miss the earlier reply on back-to-back posts and would
  change the `InferenceService` Protocol). No separate `PromptPipeline` service.
- **`OllamaClient.chat(messages, *, model=None) -> str`** holds the current `/api/chat`
  body and error handling. `generate(prompt, *, model=None)` becomes
  `return self.chat([{"role": "user", "content": prompt}], model=model)`. `chat` is added to
  the `IntelligenceClient` Protocol.
- **New in `app/intelligence/prompt_builders.py`:** `VOICE_CONFIGS_PATH`,
  `load_voice_configs`, `DM_ROLE_PROMPT`, `build_system_prompt`, `build_chat_messages`.
- **Deleted:** `build_game_chat_prompt`, `build_game_state_payload`, `build_turn_summary`
  (and the then-unused `Iterable` import) from `prompt_builders.py`; the whole file
  `app/intelligence/writer.py` (and its mentions in `app/intelligence/__init__.py`).
- **Kept exactly as they are:** `build_narrator_prompt`, `build_adjudicator_prompt`,
  `NarratorVoiceParams`, `_truncate`, `_compact_json`, `_verbosity_to_sentences`,
  `world_guide.py`, `quest_guide.py`, `app/intelligence/tools/*`.
- **Renamed:** `app/intelligence/voice_configs/voice_congfigs.json` ->
  `voice_configs.json` (contents byte-identical).
- **Fixed:** `app/intelligence/prompts.py` line 1 `from prompting import (` ->
  `from app.intelligence.prompting import (`.
- **Not touched:** `app/services/messages.py`, `app/api/v1/ws.py`, `app/api/v1/session.py`,
  `app/type_defs.py`, `app/config.py`, `settings.json`, `generate_tokens`, `enqueue`,
  `InferenceJob`, `_append_reply`, `_update_message_status`.

### Verified facts (checked against the tree on 2026-10-11)
- Next free spec number is 0006 (`docs/specs/` holds SPEC-0001..SPEC-0005).
- `OllamaClient.generate` today posts `{"model", "messages": [{"role": "user", "content": prompt}], "stream": False}`
  to `{base_url}/api/chat` via `httpx.post`; 404 -> `IntelligenceError("Intelligence request failed: model '<m>' not found. Available: ...")`
  (calls `httpx.get(.../api/tags)`); other HTTP status -> `IntelligenceError` with response text;
  any other exception -> `IntelligenceError("Intelligence request failed: <exc>")`;
  empty content -> `IntelligenceError("Intelligence endpoint returned an empty response.")`.
- `_worker_loop` currently calls `self.client.generate(job.prompt)`; `job.prompt` equals the
  user's `content` (`submit_user_message` passes `prompt=payload["content"]`). Messages become
  `completed` only after the worker finishes them, and the worker is a single FIFO thread, so
  when job N runs, the user message and reply of every job before it are already stored.
  The current message has status `running` when the history is read.
- `SqliteSessionStore.list_messages(session_id)` returns fresh dicts in `ORDER BY seq` order with
  keys `id, client_message_id, role, content, status, meta, created_at, updated_at`; for an
  unknown session it returns `[]` (no `KeyError`).
- `app/services/messages.py` (`submit_user_message`) is the single entry for REST and WS; the WS
  handler (`ws.py::_handle_user_message`) calls it and then only polls the store, so no transport
  change is needed. `generate_tokens` (WS streaming stub) is not reached by `ws.py`; it still
  calls `client.generate(prompt)` and is REQ-0007's.
- `app/intelligence/prompts.py` uses `from prompting import ...` (a top-level module that does not
  exist on `sys.path`), so `import app.intelligence.prompts` currently raises `ModuleNotFoundError`.
- `app/intelligence/world_guide.py` imports `_compact_json` from `.prompt_builders`; that helper
  MUST stay. `app/intelligence/tools/narrate.py` imports `build_narrator_prompt` lazily (inside
  `run`); it stays untouched.
- `app/intelligence/__init__.py` imports `writer` (with `# noqa: F401`), lists `"writer"` in
  `__all__`, and mentions it in the docstring.
- `app/intelligence/prompt_builders.py` already defines `logger = get_logger(__name__)` (currently
  unused) and a module docstring that names `build_game_chat_prompt`.
- `PromptSettings(enable_narration, enable_adjudication, verbosity_default="normal", dm_voice: PromptVoiceSettings)`;
  `PromptVoiceSettings(tone="neutral", persona="classic_dm", sensory_focus="balanced", consequence_level="moderate")`;
  `AppSettings.max_turns=6`, `max_field_len=240`. `settings.json` has the same values.
- Voice config file keys: `dm_voice`, `dm_analysis`, `player_voice`, `player_journal` (all strings).
- `tests/session_helpers.make_stub_service()` builds `OllamaInferenceService(types.SimpleNamespace(ollama=...))`
  (only `ollama`); `tests/conftest.py::stub_svc` and every worker-path test in
  `tests/test_inference_reply.py` patch `svc.client.generate` with `lambda prompt, **kw: ...`
  (or a `boom`/`fail_if_called` function with the same signature).
- Guard tests scanning `app/`: `test_single_session_model.test_no_references_to_removed_symbols`
  (new code MUST NOT contain `SessionService`, `GameService`, `session_service`, `game_service`,
  `SessionEntry`) and `test_logging_consistency` (no `logging.getLogger(` outside `logger.py`).
- Tooling: Python 3.13, `ruff check app tests`, `black --check app tests` (line length 100),
  `pytest` with `asyncio_mode = "auto"`; run `./venv-dnd-server/bin/python -m pytest -q`.

### Exact formats fixed by this spec (so tests and code agree)
- `DM_ROLE_PROMPT` (module constant in `prompt_builders.py`):
  `"You are the Dungeon Master of a D&D 5e game. Narrate the world, play its characters, and respond to the player's actions without deciding what the player does."`
- `build_system_prompt(prompts, voice_configs) -> str` returns the non-empty parts joined with
  `"\n\n"`, in this order: (1) `DM_ROLE_PROMPT`; (2) `voice_configs["dm_voice"]` only if the key is
  present and a non-empty string; (3) the voice line
  `"VOICE: TONE:{tone}|PERSONA:{persona}|VERBOSITY:{verbosity_default}|SENSE:{sensory_focus}|CONSEQ:{consequence_level}"`
  built from `prompts.dm_voice.tone`, `.persona`, `.sensory_focus`, `.consequence_level` and
  `prompts.verbosity_default`. With default settings and the real voice file the voice line is
  `VOICE: TONE:neutral|PERSONA:classic_dm|VERBOSITY:normal|SENSE:balanced|CONSEQ:moderate`.
- `build_chat_messages(system, history, current_message_id, current_text, *, max_turns, max_field_len)`
  returns `[{"role": "system", "content": system}, *prior, {"role": "user", "content": current_text}]`.
  `prior`: take `history` in the given order, stop at the first message whose `id == current_message_id`
  (if no message has that id, use all of `history`), keep those with `status == "completed"` and
  `role in ("user", "assistant")`, keep the **last** `max_turns` of them (none when `max_turns <= 0`),
  oldest first, each as `{"role": m["role"], "content": _truncate(m.get("content"), max_field_len)}`.
  The current text is NOT truncated. Every returned item has exactly the keys `role` and `content`.
  The `history` argument and its dicts are not mutated.
- `load_voice_configs(path=VOICE_CONFIGS_PATH) -> dict[str, str]`: on missing file, unreadable file,
  invalid JSON, or a top-level value that is not a dict -> log one WARNING
  (`logger.warning("voice_configs.unavailable", extra={"path": str(path), "reason": "<missing|invalid_json|not_object|unreadable>"})`)
  and return `{}`. If the top level is a dict, entries whose key or value is not a `str` are dropped
  (one WARNING `"voice_configs.entry_dropped"` with `extra={"key": str(key)}` per dropped entry)
  and the remaining entries are returned. Never raises. Never logs file contents.
- Worker log line (counts only): `logger.info("prompt.built", extra={"session_id": ..., "message_id": ..., "history_count": len(messages) - 2, "message_count": len(messages)})`.

### Discrepancies between the architect output and the code (reported, not silently fixed)
1. **Work-package order.** The requested order puts "inference_service wiring" before
   "test-helper updates". That breaks the suite in between: once the worker calls `chat`,
   `make_stub_service()` (SimpleNamespace without `prompts`/`app`) raises `AttributeError` in
   `__init__`, and every worker-path test that patches `generate` stops patching what the worker
   calls. The helper/stub updates are safe to land *before* the wiring (a patched `chat` still
   intercepts `generate`, because `generate` delegates to `self.chat`; a real `Settings` works with
   the old service). This spec therefore orders test-helper updates (WP-6) **before** wiring (WP-7).
   The design itself is unchanged and feasible.
2. **`prompt_builders.py` module docstring** names `build_game_chat_prompt` and the old
   `intelligence.prompt_builders` import path. The architect did not list it; WP-3 rewrites it
   (docstring only) so it does not mention a deleted symbol.
3. **`load_voice_configs(path=VOICE_CONFIGS_PATH)`** binds the default at definition time, so a test
   cannot redirect the default by monkeypatching the constant. Tests pass `path=` explicitly
   (loader tests) or monkeypatch `app.services.inference_service.load_voice_configs` (service tests).
   No design change.
4. **`_truncate(s, n)` with `n <= 0`** returns `s[: n - 1] + "…"` (e.g. `n=0` drops the last character
   and appends an ellipsis). The architect keeps `_truncate` untouched and `max_field_len` defaults
   to 240, so this is only reachable by a bad `settings.json`. Recorded as gate G-6; no guard added.
5. **Out-of-pipeline raw-prompt call sites remain:** `generate_tokens` (`client.generate(prompt)`,
   REQ-0007) and `app/intelligence/tools/narrate.py` (calls `build_narrator_prompt` with kwargs it does
   not accept and `inference.generate`, which `OllamaInferenceService` does not define; REQ-0008).
   Neither is reached by REST or WS message flow, so REQ-0006 is satisfiable without touching them.
   Reported only.
6. **User messages whose job ended `error`/`cancelled` are excluded from later history** (only
   `completed` messages are included). This follows from the architect's rule and the requirement
   ("completed prior messages"); noted as gate G-6.

## 2. Test Spec
Written first. No test needs network or Ollama: HTTP is replaced by monkeypatching
`httpx.post` / `httpx.get`, and `client.chat` is replaced on the service instance. Run all with
`./venv-dnd-server/bin/python -m pytest -q`. Four new files plus edits to existing ones.

### 2.1 `tests/test_ollama_client.py` (new; WP-8)
Fake HTTP: a tiny `_Resp` (or `httpx.Response(status, json=..., request=httpx.Request("POST", url))`)
returned by a monkeypatched `httpx.post` that records `url`, `json`, `timeout`.

- **T-01 chat sends the list verbatim.** `OllamaClient("http://h:1/", "m1", 7.0).chat(msgs)` with a
  3-item `msgs` -> `httpx.post` called once with URL `http://h:1/api/chat`, `json == {"model": "m1", "messages": msgs, "stream": False}`,
  `timeout == 7.0`; returns the response's `message.content`.
- **T-02 chat model override.** `chat(msgs, model="m2")` -> posted `json["model"] == "m2"`.
- **T-03 generate delegates to chat.** `generate("hi")` posts `json["messages"] == [{"role": "user", "content": "hi"}]`
  and returns the content; `generate("hi", model="m2")` posts model `m2`. Also: with `chat` monkeypatched on the
  instance, `generate("hi", model="m2")` calls `chat([{"role": "user", "content": "hi"}], model="m2")` exactly once.
- **T-04 HTTP errors map to `IntelligenceError`.** A 404 response -> `IntelligenceError` whose message contains
  `model 'm1' not found` (patch `httpx.get` to return a tags payload or raise; message still produced); a 500 response
  with body text -> `IntelligenceError` whose message contains that text.
- **T-05 transport and empty-content errors.** `httpx.post` raising `httpx.ConnectError` -> `IntelligenceError`;
  a 200 response with `{"message": {"content": ""}}` -> `IntelligenceError` containing `empty response`.
- **T-06 Protocol.** `IntelligenceClient` declares both `chat` and `generate` (`hasattr` on the Protocol class);
  `OllamaClient` has both callables.

### 2.2 `tests/test_prompt_builders.py` (new; WP-9)
Uses literal dicts, `Settings().prompts` and `PromptSettings(...)` from `app.config`.
Helper `_m(id, role, content, status="completed")` returns `{"id", "role", "content", "status", "meta": {}}`.

- **T-07 system prompt, full.** `build_system_prompt(Settings().prompts, {"dm_voice": "VOICE-SENTENCE"})` contains
  `DM_ROLE_PROMPT`, `VOICE-SENTENCE`, and the substring `TONE:neutral|PERSONA:classic_dm|VERBOSITY:normal|SENSE:balanced|CONSEQ:moderate`;
  `DM_ROLE_PROMPT` appears before `VOICE-SENTENCE`, which appears before the voice line.
- **T-08 system prompt, empty voice configs.** `build_system_prompt(Settings().prompts, {})` is a non-empty `str`
  containing `DM_ROLE_PROMPT` and the voice line; also `{"dm_voice": ""}` and `{"other": "x"}` add nothing
  (result equals the `{}` result).
- **T-09 system prompt reflects settings.** With `PromptSettings(verbosity_default="long", dm_voice=PromptVoiceSettings(tone="grim", persona="p", sensory_focus="smell", consequence_level="harsh"))`
  the result contains `TONE:grim|PERSONA:p|VERBOSITY:long|SENSE:smell|CONSEQ:harsh`.
- **T-10 message order.** Two completed prior messages `u0` (user), `a0` (assistant) and current id `u1`, text `"now"` ->
  `[system, u0, a0, current]` with roles `system, user, assistant, user`; `[0]["content"] == system`; `[-1] == {"role": "user", "content": "now"}`.
- **T-11 filtering.** History: completed user, completed assistant, a `queued` user, a `running` user, an `error` user,
  a `cancelled` assistant, a completed message with role `"system"`, the current message (id `cur`, status `running`),
  and a completed message placed AFTER the current one. Result contains only system + the two eligible completed
  user/assistant messages + current. (Nothing after the current message; nothing with another status or role.)
- **T-12 max_turns cap.** 10 completed prior messages `m0..m9`, `max_turns=4` -> prior is exactly `m6..m9` in that
  (oldest first) order; total length 6. `max_turns=100` -> all 10 kept.
- **T-13 max_turns <= 0.** `max_turns=0` and `max_turns=-3` -> exactly `[system, current]` even with non-empty history
  (guards against `lst[-0:]`).
- **T-14 empty history, no campaign.** `history=[]` -> `[system, current]`; the function signature has no
  campaign-like parameter (`inspect.signature(build_chat_messages).parameters` keys are exactly
  `system, history, current_message_id, current_text, max_turns, max_field_len`).
- **T-15 truncation.** A prior message of 500 chars with `max_field_len=20` -> its `content == _truncate(text, 20)`
  (length 20, ends with `…`); a prior message of exactly 20 chars is unchanged; a current text of 500 chars is
  returned untruncated.
- **T-16 unknown current id.** `current_message_id="ghost"` (not in history) -> all eligible completed messages are
  used as prior (still capped by `max_turns`).
- **T-17 plain dicts only; no mutation.** History dicts that contain only `id, role, content, status` work (no
  other keys needed); a deep copy of `history` taken before the call equals `history` after; every returned item's
  keys are exactly `{"role", "content"}`.
- **T-18 loader, real file.** `load_voice_configs()` returns a dict with keys `dm_voice`, `dm_analysis`, `player_voice`,
  `player_journal`, all non-empty `str`; `VOICE_CONFIGS_PATH.name == "voice_configs.json"` and the path exists.
- **T-19 loader, missing file.** `load_voice_configs(tmp_path / "nope.json")` -> `{}` and exactly one WARNING record from
  logger `app.intelligence.prompt_builders` (use `caplog.at_level(logging.WARNING, logger="app.intelligence.prompt_builders")`).
- **T-20 loader, invalid JSON.** A file containing `{not json` -> `{}` and one WARNING; no exception.
- **T-21 loader, not an object.** A file containing `["a", "b"]` -> `{}` and one WARNING.
- **T-22 loader, bad entries dropped.** A file `{"dm_voice": 3, "ok": "fine", "n": null}` -> `{"ok": "fine"}` and a WARNING
  for each dropped entry; the file's text never appears in any log record.

### 2.3 `tests/test_prompt_pipeline.py` (new; WP-10)
Worker/REST/WS integration with a recording stub: `calls: list[list[dict]] = []`;
`def _chat(messages, **kw): calls.append(copy.deepcopy(messages)); return f"reply-{len(calls)}"`;
installed with `monkeypatch.setattr(svc.client, "chat", _chat)`. Use `wait_idle` from `tests/session_helpers.py`.

- **T-23 worker sends the built list.** Store `s1` with `u0` "earlier question" (completed), `a0` assistant "earlier answer"
  (completed), then `u1` "hello" (set `u0`/`a0` to completed via `update_message_status`); `svc.enqueue(..., prompt="hello")`;
  after `wait_idle`, `calls == [[{"role": "system", "content": S}, {"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}, {"role": "user", "content": "hello"}]]`
  where `S == build_system_prompt(Settings().prompts, load_voice_configs())`. The reply `reply-1` is stored as the new
  assistant message (REQ-0003 semantics unchanged).
- **T-24 REST shares the path and sees earlier replies.** With `stub_client`/`stub_svc` (and `stub_svc.client.chat` replaced by
  the recorder), POST `/api/v1/sessions`, then POST two messages `"first"`, `"second"` back-to-back (no wait between), then
  `wait_idle`. `calls[0]` is `[system, user "first"]`; `calls[1]` is
  `[system, user "first", assistant "reply-1", user "second"]`.
- **T-25 WS shares the path and sees earlier replies.** Same as T-24 but sending two `{"action": "user_message", "text": ...}`
  frames over `stub_client.websocket_connect(...)`, reading `snapshot`, then per message `entry`, `entry`, `done`. `calls[1]`
  has the same shape as in T-24, with the WS texts.
- **T-26 settings limits honoured.** `make_stub_service(app=AppSettings(max_turns=2, max_field_len=10))`; store with 4 completed
  prior messages, the last two having 40-char contents; enqueue the current message -> `calls[0]` has `system`, exactly the last
  2 prior messages with content `_truncate(content, 10)`, then the current text in full.
- **T-27 no campaign context needed.** A brand-new session with a single message (no history) -> `calls[0] == [system, {"role": "user", "content": "hello"}]`
  and `calls[0][0]["role"] == "system"`. No campaign data exists anywhere in the test.
- **T-28 prompt text is never logged.** With `caplog.at_level(logging.INFO)`, a history message and a current message both
  containing the sentinel `SENTINEL-7f3a` -> after `wait_idle` no log record has the sentinel in `getMessage()` or in
  `str(record.__dict__)`; a `prompt.built` record exists with `history_count` and `message_count` ints.
- **T-29 service survives an empty voice config.** `monkeypatch.setattr("app.services.inference_service.load_voice_configs", lambda: {})`
  before `make_stub_service()`; the request's `calls[0][0]["content"]` contains `DM_ROLE_PROMPT` and the voice line, and the job
  completes.
- **T-30 existing suites stay green with `chat` stubs.** After WP-6 and WP-7, all tests in `tests/test_inference_reply.py`
  (worker path), `tests/test_session_rest.py`, `tests/test_ws_session.py`, `tests/test_messages_helper.py`,
  `tests/test_sqlite_store.py`, `tests/test_single_session_model.py` and `tests/test_logging_consistency.py` pass unchanged in
  assertions (only the patched attribute changes from `generate` to `chat`).

### 2.4 `tests/test_prompt_cleanup.py` (new; WP-11)
- **T-31 prompts.py imports cleanly.** `importlib.import_module("app.intelligence.prompts")` succeeds; its
  `build_session_prompt`, `build_world_guidance_prompt`, `WORLD_GUIDANCE_MODES` are the same objects as in
  `app.intelligence.prompting`; calling `build_world_guidance_prompt(mode="Clarify", step_name="x", answers={})` returns a `str`.
- **T-32 writer is gone.** `importlib.import_module("app.intelligence.writer")` raises `ModuleNotFoundError`; the file
  `app/intelligence/writer.py` does not exist; `"writer"` is not in `app.intelligence.__all__`; `import app.intelligence` still works.
- **T-33 dead builders gone, kept builders kept.** `prompt_builders` has no attribute `build_game_chat_prompt`,
  `build_game_state_payload`, `build_turn_summary`; it still has `build_narrator_prompt`, `build_adjudicator_prompt`,
  `NarratorVoiceParams`, `_truncate`, `_compact_json`, `_verbosity_to_sentences`, `load_voice_configs`, `build_system_prompt`,
  `build_chat_messages`; `from app.intelligence.world_guide import WorldGuide` still works; the source text of `app/` contains
  none of `build_game_chat_prompt`, `build_game_state_payload`, `build_turn_summary`, `intelligence.writer`.
- **T-34 voice file renamed.** `app/intelligence/voice_configs/voice_configs.json` exists and parses to a dict with the four keys;
  `app/intelligence/voice_configs/voice_congfigs.json` does not exist; the string `voice_congfigs` appears in no `app/**/*.py` file.

Test count: **34** (T-01..T-34). T-01..T-29 and T-31..T-34 are new tests; T-30 is the regression group over existing files.

## 3. Work Packages
Order matters (each WP leaves the tree importable and the existing suite green). Run after every WP:
`./venv-dnd-server/bin/python -m pytest -q`, `./venv-dnd-server/bin/python -m ruff check app tests`,
`./venv-dnd-server/bin/python -m black --check app tests`. Do not run git commands. Do not implement anything outside the
named files.

### WP-1: `OllamaClient.chat`, `generate` delegation, Protocol update
- **Files:** `app/intelligence/client.py` (edit only).
- **Inputs:** the current `OllamaClient.generate` (posts `{"model", "messages": [{"role": "user", "content": prompt}], "stream": False}`
  to `{base_url}/api/chat`, maps errors to `IntelligenceError`) and the `IntelligenceClient` Protocol with only `generate`.
- **Outputs:**
  1. `OllamaClient.chat(self, messages: list[dict[str, str]], *, model: str | None = None) -> str` containing the whole current body of
     `generate` with `"messages": messages` instead of the one-element list (same URL, same `"stream": False`, same timeout, same
     404/other-HTTP/other-exception/empty-content handling and messages, same `logger.error`/`logger.exception` calls; never log the
     message contents).
  2. `generate(self, prompt: str, *, model: str | None = None) -> str` reduced to
     `return self.chat([{"role": "user", "content": prompt}], model=model)`.
  3. `IntelligenceClient` Protocol gains `def chat(self, messages: list[dict[str, str]], *, model: str | None = None) -> str: ...`
     (keep `generate`).
  4. Update the module docstring line "Keep a simple sync interface `generate(prompt, model=None) -> str`" to mention `chat(messages, model=None)` too.
- **Acceptance criteria:**
  - `OllamaClient("http://h:1", "m", 5).chat([{"role": "user", "content": "x"}])` posts that exact list to `http://h:1/api/chat` with
    `stream: False`, default model `m`, timeout 5, and returns the content string (verify by monkeypatching `httpx.post`).
  - `chat(..., model="z")` posts model `z`.
  - `generate("hi")` posts `messages == [{"role": "user", "content": "hi"}]` (same request body as before this change) and returns the same string.
  - HTTP 404 / other HTTP error / transport exception / empty content raise `IntelligenceError` with the same messages as before.
  - `IntelligenceClient` has both `chat` and `generate`.
  - No other file changed; existing test suite still green (it patches `generate`, which still exists).
- **Makes pass:** T-01..T-06 once WP-8 exists.
- **Patterns used/created:** PAT-ARCH-003 (item 6, applied), PAT-CODE-001 (applied; no new logger use).

### WP-2: Rename the voice config file; add `VOICE_CONFIGS_PATH` and `load_voice_configs`
- **Files:** `app/intelligence/voice_configs/voice_congfigs.json` (delete) and `app/intelligence/voice_configs/voice_configs.json`
  (create with byte-identical contents; i.e. a rename); `app/intelligence/prompt_builders.py` (edit: add code only).
- **Inputs:** the existing JSON file with keys `dm_voice`, `dm_analysis`, `player_voice`, `player_journal`; `prompt_builders.py` already has
  `from app.services.logger import get_logger` and `logger = get_logger(__name__)`.
- **Outputs:**
  1. Renamed file (same four keys and strings; old name no longer exists).
  2. In `prompt_builders.py` (`import json` is already present): add `from pathlib import Path`; add
     `VOICE_CONFIGS_PATH = Path(__file__).resolve().parent / "voice_configs" / "voice_configs.json"`; add
     `def load_voice_configs(path: Path | str = VOICE_CONFIGS_PATH) -> dict[str, str]` implementing exactly the loader contract in
     "Exact formats fixed by this spec" (missing/unreadable/invalid JSON/non-dict -> one WARNING `voice_configs.unavailable` with
     `extra={"path": str(path), "reason": ...}` and `{}`; non-`str` keys/values dropped with one WARNING `voice_configs.entry_dropped`
     each; never raises; never logs file contents). Use the module-level `logger` only (no `logging.getLogger`, no `print`).
     Read with `encoding="utf-8"`. Do not touch any other function.
- **Acceptance criteria:**
  - `load_voice_configs()` returns a dict with exactly the keys `dm_voice`, `dm_analysis`, `player_voice`, `player_journal`, all non-empty strings.
  - `load_voice_configs(<missing path>)`, `(<file with "{not json">)`, `(<file with '["a"]'>)` each return `{}` and emit a WARNING record from logger
    `app.intelligence.prompt_builders`, and never raise.
  - `load_voice_configs(<file with '{"dm_voice": 3, "ok": "fine"}'>)` returns `{"ok": "fine"}` with a WARNING for the dropped entry.
  - `voice_congfigs.json` no longer exists; `voice_configs.json` does.
  - Nothing else in `app/` mentions the string `voice_congfigs`.
  - Existing suite green.
- **Makes pass:** T-18..T-22, T-34 once WP-9/WP-11 exist.
- **Patterns used/created:** PAT-ARCH-003 (item 4), PAT-CODE-001.

### WP-3: Add `build_system_prompt` and `build_chat_messages`; delete the three dead builders
- **Files:** `app/intelligence/prompt_builders.py` (edit only).
- **Inputs:** `_truncate(s, n)` already exists in the file (keep as is); `PromptSettings` lives in `app.config`; WP-2's additions already present
  (or at least do not conflict: this WP does not touch them).
- **Outputs:**
  1. Add `from app.config import PromptSettings` (top-level import; `app.config` imports nothing from `app`, so no cycle).
  2. Add module constant `DM_ROLE_PROMPT` with exactly the string in "Exact formats fixed by this spec".
  3. Add `def build_system_prompt(prompts: PromptSettings, voice_configs: dict[str, str]) -> str` returning the parts joined by `"\n\n"`
     exactly as specified: `DM_ROLE_PROMPT`, then `voice_configs["dm_voice"]` only if present and a non-empty `str`, then
     `VOICE: TONE:{prompts.dm_voice.tone}|PERSONA:{prompts.dm_voice.persona}|VERBOSITY:{prompts.verbosity_default}|SENSE:{prompts.dm_voice.sensory_focus}|CONSEQ:{prompts.dm_voice.consequence_level}`.
  4. Add `def build_chat_messages(system: str, history: list[dict[str, Any]], current_message_id: str, current_text: str, *, max_turns: int, max_field_len: int) -> list[dict[str, str]]`
     with exactly the semantics in "Exact formats fixed by this spec": prior = messages before the first one with `id == current_message_id`
     (all of them if none matches), `status == "completed"`, `role in ("user", "assistant")`; keep the last `max_turns` (none if `max_turns <= 0`; do
     NOT write `lst[-max_turns:]` without the `<= 0` guard); oldest first; `content=_truncate(m.get("content"), max_field_len)`; current text not
     truncated; items have only `role` and `content`; inputs not mutated; no I/O, no store access, no campaign parameter, no ORM attribute access.
  5. Delete `build_game_chat_prompt`, `build_game_state_payload` and `build_turn_summary` entirely, and delete `from collections.abc import Iterable`
     (ruff F401 otherwise). Keep `json`, `dataclass`, `Any`, `logger`, `_truncate`, `_compact_json`, `_verbosity_to_sentences`, `NarratorVoiceParams`,
     `build_adjudicator_prompt`, `build_narrator_prompt` untouched.
  6. Rewrite the module docstring (docstring only) to describe: narrator/adjudicator prompt builders plus the chat pipeline
     (`build_system_prompt`, `build_chat_messages`, `load_voice_configs`); it must not name any deleted function.
- **Acceptance criteria:**
  - `build_chat_messages("S", history, "cur", "now", max_turns=2, max_field_len=10)` returns `[{"role": "system", "content": "S"}, <last 2 eligible prior>, {"role": "user", "content": "now"}]`
    where eligible = before `cur`, `status == "completed"`, role user/assistant, contents cut to 10 chars with `_truncate`.
  - `max_turns=0` or negative yields only `[system, current]`; empty history yields `[system, current]`; unknown current id uses all eligible messages.
  - `build_system_prompt(Settings().prompts, {})` is non-empty and contains `DM_ROLE_PROMPT` and `TONE:neutral|PERSONA:classic_dm|VERBOSITY:normal|SENSE:balanced|CONSEQ:moderate`;
    with `{"dm_voice": "X"}` it also contains `X` between the role sentence and the voice line.
  - `hasattr(prompt_builders, "build_game_chat_prompt" | "build_game_state_payload" | "build_turn_summary")` is False; `build_narrator_prompt`,
    `build_adjudicator_prompt`, `NarratorVoiceParams`, `_truncate`, `_compact_json`, `_verbosity_to_sentences` still exist and behave as before.
  - `from app.intelligence.world_guide import WorldGuide` still imports.
  - `ruff check app` clean (no unused import); the whole existing suite green. (`app/intelligence/writer.py` still imports `build_game_chat_prompt` at this point
    and WOULD break `import app.intelligence`; so **WP-4 MUST land in the same change as WP-3**, or WP-4 first. See WP-4.)
- **Makes pass:** T-07..T-17, T-33 once WP-9/WP-11 exist.
- **Patterns used/created:** PAT-ARCH-003 (items 1-3).

### WP-4: Delete `writer.py` and clean `app/intelligence/__init__.py`
- **Files:** `app/intelligence/writer.py` (delete); `app/intelligence/__init__.py` (edit).
- **Inputs:** `writer.py` is a 7-line alias module re-exporting `build_adjudicator_prompt, build_game_chat_prompt, build_narrator_prompt`; `__init__.py` imports
  `writer` inside `from app.intelligence import (client, prompt_builders, tool_handler, world_guide, writer,  # noqa: F401)`, has `"writer"` in `__all__`, and a docstring
  line `- writer.py        : Thin alias surface for session prompt builder`.
- **Outputs:** `writer.py` removed; in `__init__.py` remove `writer` from the import block (drop the `# noqa: F401` only if no longer needed; keep the other imports and
  `from . import tools`), from `__all__`, and delete the docstring line mentioning `writer.py`; also fix the docstring line for `prompt_builders` if it mentions
  the deleted builders (it says "narration, adjudicator, session" -> change to "narration, adjudicator, chat pipeline").
- **Acceptance criteria:**
  - `import app.intelligence` works; `app.intelligence.__all__ == ["client", "prompt_builders", "tools", "tool_handler", "world_guide"]`.
  - `import app.intelligence.writer` raises `ModuleNotFoundError`; the file does not exist.
  - No file in `app/` or `tests/` mentions `intelligence.writer`, `from .writer`, or imports `writer` (search `app/` and `tests/` text before finishing and report any hit instead of
    editing outside this WP's files).
  - Existing suite green. **Land WP-3 and WP-4 together** (the dead builder is imported by `writer.py` until it is deleted).
- **Makes pass:** T-32 (and part of T-33) once WP-11 exists.
- **Patterns used/created:** none.

### WP-5: Fix the `prompts.py` import
- **Files:** `app/intelligence/prompts.py` (edit, one line).
- **Inputs:** line 1 is `from prompting import (` followed by `WORLD_GUIDANCE_MODES, build_session_prompt, build_world_guidance_prompt,` and an `__all__` of the same three names.
- **Outputs:** line 1 becomes `from app.intelligence.prompting import (`; nothing else changes (do not touch `prompting.py`).
- **Acceptance criteria:**
  - `import app.intelligence.prompts` succeeds (it raised `ModuleNotFoundError` before).
  - `app.intelligence.prompts.build_session_prompt is app.intelligence.prompting.build_session_prompt` (and likewise for the other two names and `WORLD_GUIDANCE_MODES`).
  - `ruff check app` clean (import sorting: the first-party import is the only import in the file).
  - Existing suite green.
- **Makes pass:** T-31 once WP-11 exists.
- **Patterns used/created:** none.

### WP-6: Test-helper and stub updates (before the wiring)
- **Files:** `tests/session_helpers.py`, `tests/conftest.py`, `tests/test_inference_reply.py` (edit only; assertions unchanged).
- **Inputs:** WP-1 is done (`OllamaClient.chat` exists and `generate` delegates to `self.chat`, so a patched `chat` intercepts both today and after WP-7).
  Today `make_stub_service()` builds `OllamaInferenceService(types.SimpleNamespace(ollama=types.SimpleNamespace(base_url="http://127.0.0.1:1", model="stub", timeout_seconds=1.0)))`;
  `conftest.stub_svc` does `monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")`; `test_inference_reply.py` patches `svc.client.generate`
  in each worker-path test with lambdas/`boom`/`fail_if_called` taking `(prompt, **kw)`.
- **Outputs:**
  1. `tests/session_helpers.py`: replace the `SimpleNamespace` with real settings. New signature
     `make_stub_service(**settings_kwargs) -> OllamaInferenceService` building
     `Settings(ollama=OllamaSettings(base_url="http://127.0.0.1:1", model="stub", timeout_seconds=1.0), **settings_kwargs)` (imports `from app.config import OllamaSettings, Settings`);
     remove the now-unused `import types`. Calling `make_stub_service()` with no arguments keeps working.
  2. `tests/conftest.py::stub_svc`: patch `"chat"` instead of `"generate"`: `monkeypatch.setattr(svc.client, "chat", lambda messages, **kw: "stub reply")`.
  3. `tests/test_inference_reply.py`: in every test that patches `svc.client.generate` (including `boom` and `fail_if_called` and the `caplog` test), patch `"chat"` instead,
     rename the lambda/function parameter `prompt` -> `messages` (`lambda messages, **kw: "stub reply"`; `def boom(messages, **kw)`; `def fail_if_called(messages, **kw)`), and update the
     `fail_if_called` assertion text to `"chat must not be called for a cancelled job"`. Do not change any assertion on store contents, statuses or meta.
- **Acceptance criteria:**
  - `make_stub_service()` returns a working service built from a real `Settings`; no `SimpleNamespace` remains in `tests/session_helpers.py`.
  - No test file still patches `svc.client.generate` for the worker path (search `tests/` for `"generate"` and report any remaining hit that is not in `tests/test_ollama_client.py`).
  - The whole existing suite is green at this point (WP-7 not yet done): i.e. the patched `chat` is reached through the old `generate(job.prompt)` call.
- **Makes pass:** T-30 (regression) together with WP-7.
- **Patterns used/created:** PAT-ARCH-003 (Consequences: "worker tests must stub `client.chat`").

### WP-7: Wire the prompt pipeline into `OllamaInferenceService`
- **Files:** `app/services/inference_service.py` (edit only).
- **Inputs:** WP-1 (`chat`), WP-2 (`load_voice_configs`), WP-3 (`build_system_prompt`, `build_chat_messages`), WP-6 (stubs use real `Settings` and patch `chat`).
  `__init__(self, settings)` builds `self.client = OllamaClient(...)` and starts the worker thread at its end; `_worker_loop` has, inside its `try`, the `job.start` log
  then `text = self.client.generate(job.prompt)`.
- **Outputs:**
  1. Imports: `from app.intelligence.prompt_builders import build_chat_messages, build_system_prompt, load_voice_configs`.
  2. In `__init__`, **before** the worker thread starts: `self._system_prompt = build_system_prompt(settings.prompts, load_voice_configs())`,
     `self._max_turns = settings.app.max_turns`, `self._max_field_len = settings.app.max_field_len`.
  3. In `_worker_loop`, inside the existing `try`, replace `text = self.client.generate(job.prompt)` with:
     `history = job.store.list_messages(job.session_id)`;
     `messages = build_chat_messages(self._system_prompt, history, job.message_id, job.prompt, max_turns=self._max_turns, max_field_len=self._max_field_len)`;
     `logger.info("prompt.built", extra={"session_id": job.session_id, "message_id": job.message_id, "history_count": len(messages) - 2, "message_count": len(messages)})`;
     `text = self.client.chat(messages)`. Counts only: never log message content or `job.prompt`.
  4. Nothing else changes: `enqueue`, `InferenceJob`, status flow (`queued`/`running`/`completed`/`error`/`cancelled`), cancellation, `_append_reply`, `_update_message_status`,
     `generate_tokens` (still `self.client.generate(prompt)`; REQ-0007), `queue_position`, `estimate_wait`, `shutdown`. No new method, no new class, no `PromptPipeline`.
     Any exception from `list_messages`/`build_chat_messages`/`chat` goes through the existing `except Exception` branch (status `error`, `meta.error`).
- **Acceptance criteria:**
  - For a store holding completed `u0` "earlier question", completed assistant `a0` "earlier answer", then queued `u1` "hello", a job for `u1` makes the stubbed
    `client.chat` receive exactly `[system, user "earlier question", assistant "earlier answer", user "hello"]` where `system` contains the DM role sentence and the voice line
    from `settings.prompts`; the reply is stored as a new assistant message with `meta.reply_to == "u1"` as before.
  - Two messages posted back-to-back through REST (or sent one after another over WS) produce a second request that includes the first user message and the first reply.
  - `settings.app.max_turns` and `settings.app.max_field_len` are honoured (a service built with `max_turns=2, max_field_len=10` sends at most 2 prior messages cut to 10 chars).
  - A session with no history works (`[system, user]`); no campaign object is read anywhere.
  - A voice-config load failure never prevents service construction (loader returns `{}`).
  - No log record from the worker contains message text.
  - A `chat` exception still ends the user message in `error` with `meta.error`; a cancelled job never calls `chat`.
  - The whole existing suite (updated by WP-6) is green; `ruff` and `black --check` clean; the `app/` guard tests still pass (no banned tokens, no `logging.getLogger(`).
- **Makes pass:** T-23..T-30 once WP-10 exists.
- **Patterns used/created:** PAT-ARCH-003 (items 1, 5, 7), PAT-ARCH-001 (applied; store API unchanged), PAT-CODE-001.

### WP-8: New tests: `tests/test_ollama_client.py`
- **Files:** `tests/test_ollama_client.py` (create).
- **Inputs:** WP-1 done. `httpx`, `pytest`, `app.intelligence.client.{OllamaClient, IntelligenceClient, IntelligenceError}`.
- **Outputs:** tests T-01..T-06 exactly as specified in section 2.1, using `monkeypatch.setattr("app.intelligence.client.httpx.post", fake_post)` (and `httpx.get` for the 404 case);
  no real network (use a base URL like `http://ollama.test:1`; the fake never opens sockets).
- **Acceptance criteria:** each of T-01 (verbatim list, URL `/api/chat`, `stream: False`, default model, timeout, returned content), T-02 (model override), T-03 (`generate` posts one `user`
  message and delegates to `chat`, model passthrough), T-04 (404 and 500 map to `IntelligenceError` with the stated message fragments), T-05 (transport error and empty content map to
  `IntelligenceError`), T-06 (`chat` and `generate` on Protocol and class) passes; the file runs in under 2 seconds with no network.
- **Makes pass:** T-01..T-06.
- **Patterns used/created:** none.

### WP-9: New tests: `tests/test_prompt_builders.py`
- **Files:** `tests/test_prompt_builders.py` (create).
- **Inputs:** WP-2 and WP-3 done. `from app.config import PromptSettings, PromptVoiceSettings, Settings`;
  `from app.intelligence.prompt_builders import DM_ROLE_PROMPT, VOICE_CONFIGS_PATH, _truncate, build_chat_messages, build_system_prompt, load_voice_configs`; pytest `tmp_path` and `caplog`.
- **Outputs:** tests T-07..T-22 exactly as in section 2.2 (helper `_m(id, role, content, status="completed")`). Loader tests pass `path=` explicitly and assert WARNING records via
  `caplog.at_level(logging.WARNING, logger="app.intelligence.prompt_builders")`.
- **Acceptance criteria:** T-07..T-22 all pass; none opens a network connection or needs Ollama; each builder test asserts the exact message list (roles and contents), not only its length.
- **Makes pass:** T-07..T-22.
- **Patterns used/created:** none.

### WP-10: New tests: `tests/test_prompt_pipeline.py`
- **Files:** `tests/test_prompt_pipeline.py` (create).
- **Inputs:** WP-6 and WP-7 done (`make_stub_service(**settings_kwargs)`, `wait_idle`, `AUTH`, fixtures `stub_svc`, `stub_client`, `session_store`; `SqliteSessionStore(":memory:")`).
- **Outputs:** tests T-23..T-29 exactly as in section 2.3 with the recording `_chat(messages, **kw)` stub installed via `monkeypatch.setattr(svc.client, "chat", _chat)`; shut services
  down with `asyncio.run(svc.shutdown())` in a fixture teardown for services created by `make_stub_service` directly (as `tests/test_inference_reply.py::svc` does).
  T-30 needs no new file (it is the existing suites).
- **Acceptance criteria:** T-23..T-29 pass: the worker sends the exact built list for a direct enqueue, via REST (two back-to-back POSTs; second call contains first user message and first
  reply) and via WS (two sequential frames; same), honours `max_turns`/`max_field_len`, needs no campaign data, logs no message text (sentinel absent from every record, `prompt.built` record
  present with int `history_count` and `message_count`), and survives an empty voice config. No network, no Ollama; the file finishes in a few seconds.
- **Makes pass:** T-23..T-29.
- **Patterns used/created:** none.

### WP-11: New tests: `tests/test_prompt_cleanup.py`
- **Files:** `tests/test_prompt_cleanup.py` (create).
- **Inputs:** WP-2, WP-3, WP-4, WP-5 done. `importlib`, `pathlib.Path`; `REPO_ROOT = Path(__file__).resolve().parents[1]`, `APP_DIR = REPO_ROOT / "app"` as in `tests/test_single_session_model.py`.
- **Outputs:** tests T-31..T-34 exactly as in section 2.4. Source-text scans read `APP_DIR.rglob("*.py")` with `encoding="utf-8"`; the test file itself is outside `app/`, so it may name the
  forbidden strings.
- **Acceptance criteria:** T-31 (`prompts` imports and re-exports the very same objects as `prompting`), T-32 (`writer` module/file gone, not in `__all__`), T-33 (three dead builders gone,
  kept builders and new functions present, `WorldGuide` importable, no mention of the deleted names or `intelligence.writer` in `app/**/*.py`), T-34 (new voice file exists and parses with the
  four keys; old misspelled file absent; `voice_congfigs` appears in no `app/**/*.py`) all pass.
- **Makes pass:** T-31..T-34.
- **Patterns used/created:** none.

## 4. Other Details
- **Risks:**
  - *Back-to-back history capture* is correct only because the worker is a single FIFO thread; if the worker is ever parallelised the "earlier reply exists" guarantee breaks
    (recorded in PAT-ARCH-003). Not a risk today.
  - *Excluded errored turns:* a user message whose job ended `error`/`cancelled` is dropped from later history (gate G-6).
  - *Message-count vs exchange-count:* `max_turns=6` is 6 messages (about 3 exchanges). Users may expect 6 exchanges (G-4).
  - *Current message not truncated:* REST caps content at 4096 chars, WS has no cap (G-3); a very long WS message goes to Ollama in full.
  - *`_truncate` with `max_field_len <= 0`* mangles content (G-6); only reachable by a bad `settings.json`.
  - *Stale reads:* voice config and settings are read once at service construction; changes need a restart (same as `settings.json`).
  - *Test-helper blast radius:* `make_stub_service` and `stub_svc` are used by many tests; WP-6 lands before WP-7 specifically to keep the suite green at each step.
  - *`generate_tokens` and `narrate.py` still send/handle raw prompts* (REQ-0007/REQ-0008); they are not reached from REST/WS message flow today.
  - *Import cycle risk:* `prompt_builders` now imports `app.config`; `app.config` imports nothing from `app`, so no cycle. If one appears, import `PromptSettings` under
    `typing.TYPE_CHECKING` and keep the annotation as a string (the module uses `from __future__ import annotations`).
- **Rollback plan:** the change is code-only and has no data or schema impact. Revert the commit(s) for WP-1..WP-11 (the order is independent for revert as a single revert);
  nothing is persisted that depends on the new code: stored messages are unchanged, no settings key is added or removed, the voice file rename reverts with the code.
  A partial rollback to the old behaviour is a one-line change in `_worker_loop` (`self.client.generate(job.prompt)`), because `generate` still works.
- **Patterns applied/created:**
  - PAT-ARCH-003 (architecture, **accepted** 2026-10-11): applied by WP-1, WP-2, WP-3, WP-7; created earlier by the architect; this spec does not change its status. After implementation, its
    "Examples" section should be updated with file/line references (a documentation step for the orchestrator after gate G-1, not a code WP).
  - PAT-ARCH-001 (accepted): applied, unchanged. PAT-ARCH-002 (accepted): unchanged. PAT-CODE-001 (accepted): applied in WP-2 and WP-7.
  - New patterns created by this spec: **none**.
- **Gates (human):**
  - **G-1** Accept PAT-ARCH-003 (`proposed` -> `accepted`). Accepted by the human on 2026-10-11 (gates G-1..G-7 all accepted as written).
  - **G-2** Confirm open question (b): `settings.prompts.enable_narration` and `enable_adjudication` are intentionally **not read** under REQ-0006 (REQ-0008 owns narrate/adjudicate).
  - **G-3** Confirm open question (c): only prior messages are truncated; the current user message is sent in full (REST caps at 4096 chars; WS has no cap).
  - **G-4** Confirm open question (d): `max_turns` counts **messages**, not exchanges (6 messages ~ 3 exchanges).
  - **G-5** Confirm open question (e): no campaign parameter or section is added until REQ-0015 builds a real campaign source.
  - **G-6** Confirm the spec-level choices not covered by the architect text: (i) bad entries in the voice file are dropped individually with a WARNING (rest kept) rather than
    discarding the whole file; (ii) messages in status `error`/`cancelled`/`queued`/`running` never appear in history; (iii) no guard for `max_field_len <= 0` (`_truncate` is untouched);
    (iv) WP order moved "test-helper updates" before "wiring" (see Discrepancy 1); (v) exact `DM_ROLE_PROMPT` wording and the `VOICE: TONE:...` line format in section 1.
  - **G-7** Do-not-change list (accepted items; this spec and its implementation MUST NOT modify them): ADR-0001, ADR-0002, ADR-0003; PAT-ARCH-001, PAT-ARCH-002, PAT-CODE-001; the
    `SessionStore` and `InferenceService` Protocols in `app/type_defs.py`; session uuid ids; message schema and status vocabulary (`queued`, `running`, `completed`, `error`, `cancelled`);
    REQ-0003 reply semantics (reply is a new assistant message with `meta.reply_to`); `app/services/messages.py`; `app/api/v1/*`.
- **Out of scope (explicit non-goals):**
  - Streaming and real token streaming, `generate_tokens` behaviour (REQ-0007).
  - Fixes to the `narrate`, `roll` and `clear` tools, `build_narrator_prompt`/`build_adjudicator_prompt` signatures, the adjudication flow (REQ-0008).
  - Auth, CORS, token validation (REQ-0009).
  - API schema changes (request/response models, OpenAPI) (REQ-0010).
  - Campaign / character / quest domain and any campaign-aware prompt section (REQ-0015).
  - Repo hygiene and the `world_guide.py` / `quest_guide.py` stubs, `app/tst.py`, `corpus.txt`, `pack_py.sh`, other stray files (REQ-0012).
  - The deleted `data/` layer and any ORM-based prompt inputs (ADR-0003).
  - New settings keys, new runtime dependencies, summarisation/token-budget trimming of history, a `PromptPipeline` service class, per-session system prompts, and changes to
    `settings.json` or `app/config.py`.
  - Updating `docs/requirements/LOG.md`, `.github/BACKLOG.json` or any ADR/pattern status (the orchestrator and human own those).
