---
id: PAT-ARCH-003
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Prompt pipeline: pure builders over store dicts, assembled by the worker at run time

## Problem
Before this pattern, the inference worker sent only the raw user text to Ollama. The
prompt builders that did exist read ORM-style attributes (`game.campaign`,
`session_run.entries[i].kind`) from a data layer that has since been deleted
(ADR-0003). Settings for voice and history limits (`settings.prompts.*`,
`settings.app.max_turns`, `settings.app.max_field_len`) and the voice config file were
never read. If prompt building moved into transports or into the enqueue path, REST and
WS could drift apart. It would also capture history before earlier replies existed.

## Context
Use this pattern for any LLM call that answers a session message: the chat reply today,
and later streaming (REQ-0007) or tool-driven narration (REQ-0008) if they build
conversational prompts. It applies on top of
[PAT-ARCH-001](./PAT-ARCH-001-session-store-single-api.md): transports stay thin, and only
the worker writes replies. It does not cover one-shot prompts that have no session
history, such as `prompting.build_session_prompt` or `build_world_guidance_prompt`. Those
may keep returning a single string.

## Solution
1. **Builders are pure functions over plain dicts.** They take store message dicts
   (`{id, role, content, status, meta, ...}` as returned by `SessionStore.list_messages`)
   plus plain values (settings models, strings, ints). They never read ORM attributes,
   never call the store, and never do I/O. They return an ordered Ollama chat list
   `[{"role": ..., "content": ...}, ...]`. They live in
   `app/intelligence/prompt_builders.py`.
2. **Order is fixed.** The list has exactly one `system` message first, then at most
   `max_turns` prior messages, then the current `user` message last. Prior messages
   are those before the current message in store order, with `status == "completed"`,
   `canon` true (NULL counts as true, ADR-0011) and `role` in {`user`, `assistant`}. When the
   current user message has `meta.narrative_only` true, prior messages with `meta.kind` admin
   are also skipped, before the `max_turns` slice (ADR-0015). They are oldest first, and each `content` is
   cut with `_truncate(..., max_field_len)`. `max_turns <= 0` means no history. Do not
   rely on `lst[-0:]`, which returns the whole list.
3. **The system message comes from configuration only.** It combines a built-in DM role
   sentence, the `dm_voice` style sentence from
   `app/intelligence/voice_configs/voice_configs.json`, and a voice line from
   `settings.prompts.dm_voice.*` and `settings.prompts.verbosity_default`, plus, when the
   session has one, a character section built by `build_character_section` from
   `SessionStore.get_character` (ADR-0008). The pipeline
   needs no campaign context. A world section is added by `build_world_section` over
   `WorldStore.list_entities` (ADR-0010, REQ-0026): canon entities selected within a
   settings chars budget, never truncated. A campaign section is added only when a real
   campaign source exists (REQ-0015). There is no speculative optional parameter before then.
4. **Config files load robustly, once.** The voice config is read once when
   `OllamaInferenceService` is constructed. A missing file, invalid JSON, or a
   non-string value is logged with `get_logger(__name__)` at WARNING (PAT-CODE-001),
   and loading falls back to `{}`. The builder then uses the built-in role sentence.
   Startup never crashes because of the voice file.
5. **The worker assembles the prompt at run time, not at enqueue time.** When the job
   runs, the worker calls `job.store.list_messages(job.session_id)`, then the builders,
   then `client.chat(messages)`. The worker is a single FIFO thread, so every earlier
   job, including its assistant reply, has finished when the next job runs. Transports
   and `app/services/messages.py` keep enqueueing `prompt=content`. The
   `InferenceService` and `SessionStore` Protocols do not change, except that the worker
   also calls `get_character` (ADR-0008) and `WorldStore.list_entities` (ADR-0010).
   Slash-command jobs (`/name args`, [PAT-ARCH-004](./PAT-ARCH-004-slash-tools-in-worker.md))
   skip the chat builder and run the tool instead.
6. **The client has two entry points and one HTTP path.**
   `OllamaClient.chat(messages, *, model=None) -> str` sends the `/api/chat` request.
   `generate(prompt, *, model=None)` is a one-line wrapper,
   `chat([{"role": "user", "content": prompt}])`, kept for tools.
   The worker's `chat` call and the inference service's `generate` run under one
   `_ollama_lock`, so Ollama calls stay serialized (ADR-0004).
7. **No prompt text in logs.** Log counts only, such as the number of history messages
   and total messages. Message content may be personal (PAT-CODE-001, PAT-ARCH-002).

## Consequences
- REST and WS share the prompt path automatically, because both reach the worker
  through `submit_user_message` and `enqueue`.
- Builders can be unit-tested with literal dicts. They need no network, Ollama, or store.
- The worker does one extra indexed `SELECT ... ORDER BY seq` per job. This is
  negligible next to LLM latency.
- Voice config and settings are read at startup, so editing them requires a restart,
  the same as `settings.json`.
- Worker tests must stub `client.chat` rather than `client.generate`.

## Examples
- `app/intelligence/prompt_builders.py`: `load_voice_configs` (line 39), `build_system_prompt`
  (line 170), `build_chat_messages` (line 187).
- `app/intelligence/client.py`: `OllamaClient.chat` (line 56); `generate` delegates to it (line 85).
- `app/services/inference_service.py`: the system prompt is built once in `__init__` (line 55)
  and the request is assembled per job in `_worker_loop` (`build_chat_messages`, line 173).
- Tests: `tests/test_prompt_pipeline.py` (worker path), `tests/test_prompt_builders.py`,
  `tests/test_ollama_client.py`.
