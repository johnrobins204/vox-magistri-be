---
id: SPEC-0023
requirement: REQ-0037
adr: ADR-0017
status: draft
date: 2026-11-08
---

# Plain chat becomes DM side-chat with tool guidance; narration moves to `/narrate`

**Owner decisions (ADR-0017 accepted; all work packages MAY be implemented in order):**
1. With narrative-only on, plain Q&A is hidden from view, as `/rules` is today.
2. No `/rule` alias; the guide uses the exact `/rules`.
3. `/narrate` gets history, character and canon world facts instead of staying one-shot.
4. `/narrate` args are not shown as "You" diary entries (already true: the diary hides user rows that have a tool reply).
5. Side-chat cards have no Edit/Regenerate (AdminCard).
6. No world-entity marks on side-chat cards.
7. The empty-log text points at `/narrate`.

## 1. Requirement
REQ-0037; restatement in `docs/requirements/LOG.md` (row REQ-0037). ADR: ADR-0017.
- Plain text (no leading `/`) is an admin side-chat: user row and reply get `meta.kind` `admin`; the reply has no `meta.tool`.
- Side-chat uses a new system message (role sentence, `dm_analysis` text, `TOOL_GUIDE`, no VOICE line) plus character, canon world and history.
- `/narrate <args>` runs the existing narrator pipeline (narrator system prompt, args as current text); its reply is `narrative`, `meta.tool` `narrate`.
- Only `/narrate` replies are mined for world entities; REST `/intel/tools/narrate/invoke` stays one-shot.
- The client counts side-chat rows and `/narrate` commands as turn starts; the empty-log text points at `/narrate`.

## 2. Test Spec
Tests are pytest under `tests/`, run per file (`./venv-dnd-server/bin/python -m pytest tests/<file>`);
write each WP's tests first and watch them fail. Reuse each file's existing fixtures
(`slash_env`, `make_svc`, `session_store`, `FakeInference`). Chat stubs record `messages` lists.
Frontend has no test runner (non-goal to add one); WP-5 is checked by `npm run build` in `frontend/`.
The full suite is not run by the spec author.

### WP-1
| Id | Exercises | Expected | File |
|---|---|---|---|
| T-1 | `message_kind(None)` | `ADMIN`; `"narrate"`, `"attack"`, `"roll"` stay `NARRATIVE`; `"rules"`, `"monster"`, `"zzz"` `ADMIN` | tests/test_message_kind.py (update existing T-1) |
| T-3 | `submit_user_message` with `{"content":"hello"}` | stored `meta.kind == "admin"`; `/narrate x` stays `narrative`; a client-sent `meta.kind` is still stripped | tests/test_message_kind.py (update T-3 case) |
| M-1 | plain submit in the messages helper | any plain-kind assertion now expects `admin` | tests/test_messages_helper.py |

### WP-2
| Id | Exercises | Expected | File |
|---|---|---|---|
| S-1 | `TOOL_GUIDE` | non-empty `str`; for each name in `ToolService(discover_on_init=True).list_tool_descriptions()` the text `/<name>` appears | tests/test_sidechat_prompt.py (new) |
| S-2 | `TOOL_GUIDE` content | contains `/rules` with a rule-name keyword hint, `/attack` with `vs`, `/narrate`; contains no `REQ-`/`SPEC-`/`ADR-` | tests/test_sidechat_prompt.py |
| S-3 | `build_sidechat_system_prompt({"dm_analysis": "X-ANALYSIS"})` | contains `SIDECHAT_ROLE_PROMPT`, `X-ANALYSIS` and `TOOL_GUIDE`, in that order, joined by blank lines; no `VOICE:`; role text forbids narration | tests/test_sidechat_prompt.py |
| S-4 | same builder with `{}`, `{"dm_analysis": ""}` and a non-str value | no exception; role sentence and guide present; no `None` text | tests/test_sidechat_prompt.py |
| S-5 | `build_system_prompt(...)` | output unchanged (still contains `DM_ROLE_PROMPT` and the `VOICE:` line) | tests/test_prompt_builders.py (keep, run) |

### WP-3
| Id | Exercises | Expected | File |
|---|---|---|---|
| W-1 | worker plain job `"hello"` | `chat_calls[0][0]["content"]` equals `build_sidechat_system_prompt(load_voice_configs())`; last message is `hello` | tests/test_prompt_pipeline.py |
| W-2 | plain reply stored | reply `meta == {"reply_to": <id>, "kind": "admin"}` (no `tool`) | tests/test_inference_reply.py, tests/test_slash_dispatch.py (`test_non_slash_messages_use_chat_path`) |
| W-3 | plain job with a character | system == side-chat prompt + `"\n\n"` + character section; with no character system is exactly the side-chat prompt | tests/test_character_wiring.py |
| W-4 | plain job with canon world entity | world section appended to the side-chat system message after the character section | tests/test_world_injection.py |
| W-5 | plain job, mining enabled | world store gets no candidate rows from the side-chat reply; `/narrate` reply still mined; `/rules`, `/roll` still not | tests/test_world_detection_worker.py (switch the chat-mining test to `/narrate`, add a plain no-mining test) |
| W-6 | history with a prior plain turn and `narrative_only` on the current user row | prior side-chat rows are absent from `chat_calls` | tests/test_prompt_pipeline.py |

### WP-4
| Id | Exercises | Expected | File |
|---|---|---|---|
| N-1 | REST and WS `/narrate a storm` (`slash_env`) | `chat_calls == [[{"role":"system","content": build_system_prompt(Settings().prompts, load_voice_configs())}, {"role":"user","content":"a storm"}]]`; reply `meta == {"tool":"narrate","reply_to":<id>,"kind":"narrative"}`; `generate` not called | tests/test_slash_dispatch.py (T-38 and WS narrate test) |
| N-2 | `/narrate` after an earlier completed turn | history message appears between system and `a storm` | tests/test_slash_dispatch.py |
| N-3 | `/narrate` with a character | system ends with the character section | tests/test_character_wiring.py |
| N-4 | `/narrate` and `/narrate   ` (empty args) | user row `error`, usage message, no chat call (ToolError path unchanged) | tests/test_slash_dispatch.py |
| N-5 | `/roll 2d6`, `/rules x`, `/monster x` | unchanged: no chat builder, replies as before | tests/test_slash_dispatch.py (existing) |
| N-6 | existing REST invoke of narrate | still one-shot through `generate` with `build_narrator_prompt` | tests/test_tool_calling.py (keep, run) |

### WP-5
| Id | Exercises | Expected | File |
|---|---|---|---|
| F-1 | `cd frontend && npm run build` | `tsc -b` and `vite build` pass | (build) |
| F-2 | manual: plain message then 7 more turns | side-chat card and its reply render; log is never empty after a side-chat only session; `/narrate x` counts as a turn | (manual) |

### WP-6
| Id | Exercises | Expected | File |
|---|---|---|---|
| P-1 | `./venv-dnd-server/bin/python -m pytest tests/test_patterns.py` | passes after the pattern and INDEX edits | tests/test_patterns.py (existing) |

## 3. Work Packages

### WP-1: Plain chat is admin (`message_kind(None)`)
- **Goal:** the plain user row is written with `meta.kind` `admin`.
- **Files:** `app/intelligence/tool_handler.py`; `tests/test_message_kind.py`; `tests/test_messages_helper.py`.
- **Inputs:** `message_kind(tool_name)` currently returns `NARRATIVE` for `None` or a name in `NARRATIVE_TOOLS` (`{"narrate","attack","roll"}`); `app/services/messages.py` calls it for every submitted user row.
- **Outputs:** `message_kind(None)` returns `MessageKind.ADMIN`; `NARRATIVE_TOOLS` unchanged; docstring says plain chat is side-chat (admin). No change to `messages.py`.
- **Failing test first:** update T-1, T-3 and M-1 as listed in this package's Test Spec; they fail on the old return value.
- **Acceptance criteria:** the tests in Test Spec WP-1 pass; a client-sent `meta.kind` is still stripped; legacy stored rows are untouched (no migration).
- **Patterns used/created:** PAT-ARCH-013 (amended by WP-6, done).

### WP-2: `TOOL_GUIDE` constant and side-chat system prompt builder
- **Goal:** add the tool guide and a pure side-chat system message builder.
- **Files:** `app/intelligence/prompt_builders.py`; `tests/test_sidechat_prompt.py` (new).
- **Inputs:** `load_voice_configs()` returns `dict[str, str]` and may contain `dm_analysis`; `DM_ROLE_PROMPT` and `build_system_prompt` exist and must not change; constants like `RULES_DIRECTIVES_GROUNDED` show the style (one `"\n".join([...])` string). Tools: `/narrate <what happens>`, `/rules <rules question naming the rule, e.g. grapple>`, `/monster <name> [2014|2024]`, `/attack <weapon> [vs <AC>]` (e.g. `/attack longsword vs 15`), `/roll [NdM+K]` (e.g. `/roll 2d6+3`).
- **Outputs:** `SIDECHAT_ROLE_PROMPT` (veteran-DM, out-of-fiction advisor to the player; must not narrate, role-play or describe scenes; points players to `/narrate` for story); `TOOL_GUIDE` (one block, one line per tool: when to suggest it, syntax, one example phrasing); `build_sidechat_system_prompt(voice_configs: dict[str, str]) -> str` = `SIDECHAT_ROLE_PROMPT`, then `dm_analysis` only when a non-empty `str`, then `TOOL_GUIDE`, joined by `"\n\n"`; no VOICE line; no I/O, never raises.
- **Failing test first:** `tests/test_sidechat_prompt.py` S-1..S-4 (S-1 fails until `TOOL_GUIDE` names every discovered tool).
- **Acceptance criteria:** tests in Test Spec WP-2 pass; `tests/test_prompt_builders.py` and `tests/test_tool_descriptions.py` still pass; guide is about 1 KB or less.
- **Patterns used/created:** PAT-ARCH-003 (pure builder); none created.

### WP-3: Worker plain-chat path uses the side-chat prompt
- **Goal:** plain text answers through the side-chat system message and is stored as admin; chat replies are no longer mined.
- **Files:** `app/services/inference_service.py`; `tests/test_prompt_pipeline.py`, `tests/test_inference_reply.py`, `tests/test_slash_dispatch.py`, `tests/test_character_wiring.py`, `tests/test_world_injection.py`, `tests/test_world_detection_worker.py`.
- **Inputs:** WP-2 provides `build_sidechat_system_prompt` in `app/intelligence/prompt_builders.py`. In `OllamaInferenceService.__init__`, `self._system_prompt = build_system_prompt(settings.prompts, load_voice_configs())`; the worker's else-branch (`name is None`) builds `system = self._system_prompt`, appends the character section, calls `build_chat_messages(...)`, `_inject_world`, `client.chat`, then `_append_reply(..., meta={"kind": MessageKind.NARRATIVE})`; the mining guard is `if name in (None, "narrate"):`.
- **Outputs:** `__init__` also builds `self._sidechat_prompt = build_sidechat_system_prompt(voice_configs)` once (load voice configs once and pass to both builders); the plain branch starts from `self._sidechat_prompt`; the plain reply meta kind is `MessageKind.ADMIN` with no `tool`; mining guard becomes `if name == "narrate":`. Character, canon injection, history and `narrative_only` handling are unchanged.
- **Failing test first:** W-1 and W-2 (in `tests/test_prompt_pipeline.py` and `tests/test_inference_reply.py`), then update the other listed tests per Test Spec WP-3.
- **Acceptance criteria:** the tests in Test Spec WP-3 pass; slash tools other than narrate are untouched; no prompt text in logs (existing log test passes).
- **Patterns used/created:** PAT-ARCH-003, PAT-ARCH-012, PAT-ARCH-013 (amended by WP-6).

### WP-4: `/narrate` runs the narrator chat pipeline in the worker
- **Goal:** `/narrate <args>` gets history, character and canon facts via the chat pipeline.
- **Files:** `app/services/inference_service.py`; `tests/test_slash_dispatch.py`; `tests/test_character_wiring.py`.
- **Inputs:** after WP-3 the worker has `detect_tool(job.prompt)` giving `(name, args)`; `name is not None` runs `self._tool_service.invoke(...)` and writes `meta={**result["meta"], "tool": name, "kind": message_kind(name)}`; else it runs the chat branch with `self._sidechat_prompt` and an admin reply. `self._system_prompt` is the narrator system message. `message_kind("narrate")` is `NARRATIVE`. `tools/narrate.py` raises `ToolError` for empty args and stays unchanged (REST invoke stays one-shot).
- **Outputs:** compute `narrate = name == "narrate" and bool((args or "").strip())`. Take the slash branch only when `name is not None and not narrate`. In the chat branch pick `system = self._system_prompt` and current text `args.strip()` when `narrate`, else `self._sidechat_prompt` and `job.prompt`; pass the current text to `build_chat_messages`. For `narrate` the reply meta is `{"tool": "narrate", "kind": message_kind("narrate")}`; otherwise the WP-3 admin meta. Empty `/narrate` still reaches `invoke` and errors with the usage text.
- **Failing test first:** N-1 (update T-38 and the WS narrate test, whose old assertion expects a one-shot `generate` prompt), then N-2..N-4.
- **Acceptance criteria:** the tests in Test Spec WP-4 pass; a `/narrate` reply is mined, a plain or other-tool reply is not; `generate` is not called for a worker `/narrate`; regenerate of a `/narrate` row works (same path, reply revised in place).
- **Patterns used/created:** PAT-ARCH-003, PAT-ARCH-004 (amended by WP-6).

### WP-5: Client turn counter and empty-log text
- **Goal:** side-chat rows and `/narrate` commands count as turn starts; the empty log points at `/narrate`.
- **Files:** `frontend/src/components/NarrativeLog.tsx`.
- **Inputs:** the `visible` memo walks messages backwards with `isTurnStart = m.role === 'user' && !isAdmin(m) && !hasTool(replies.get(m.id))`; `replies` maps user id to reply via `replyIndex`; `hasTool(msg)` tests `typeof msg?.meta?.tool === 'string'`; the empty state is `<p className="empty">The table is quiet. Describe your first move.</p>`.
- **Outputs:** a turn start is a `user` row with no tool reply (admin or not) or whose reply has `meta.tool === 'narrate'`; other tool commands (`/rules`, `/roll`, ...) still do not start turns. Empty text becomes `The table is quiet. Use /narrate to describe your first move.` No other change; no edit/regenerate or entity marks on AdminCard.
- **Failing test first:** none runnable (no frontend runner); first reproduce by rendering a log of only side-chat rows to see it empty, then `npm run build` and manual check F-2.
- **Acceptance criteria:** F-1 passes; F-2 behaves as stated: a log with only side-chat or only `/narrate` turns is not empty and older turns beyond six collapse correctly.
- **Patterns used/created:** PAT-ARCH-013 (reader uses `meta`, never content), PAT-ARCH-014 unchanged.

### WP-6: Pattern amendments (accepted by the owner)
- **Goal:** apply the owner-accepted ADR-0017 pattern wording. **Done** (pattern files and INDEX rows edited).
- **Files:** `docs/patterns/architecture/` files for PAT-ARCH-003, PAT-ARCH-004, PAT-ARCH-012, PAT-ARCH-013; `docs/patterns/INDEX.md` (their summary rows).
- **Inputs:** `docs/adr/0017-plain-chat-side-chat-narrate-only.md` section "Pattern Impact" lists the four amendments verbatim in intent.
- **Outputs:** PAT-ARCH-013 rule 2 (no tool = plain chat = admin; `NARRATIVE_TOOLS` narrative, others admin); PAT-ARCH-012 rule 3 (`/narrate` replies only); PAT-ARCH-003 rules 3 and 5 (two system messages; `/narrate` jobs use the chat builder with args as current text; other slash jobs skip it); PAT-ARCH-004 rule 3 (worker routes `/narrate` to the PAT-ARCH-003 pipeline, not `invoke`; reply meta unchanged); INDEX summaries match.
- **Failing test first:** none new; `tests/test_patterns.py` is the guard (P-1).
- **Acceptance criteria:** P-1 passes; no other pattern text changes.
- **Patterns used/created:** amends the four above; creates none.

## 4. Other Details
- **Risks:** with the toggle off, side-chat advice enters narrator history (existing semantics); prior `/narrate ...` command text appears as a user line in history; small models may still narrate in side-chat; `TOOL_GUIDE` can drift from tool syntax (tests only catch names).
- **Rollback plan:** revert WP-1, 3, 4, 5 commits (no migration, no dependency); legacy rows keep their stored kind; WP-6 reverted separately.
- **Patterns applied/created:** PAT-ARCH-003, 004, 012, 013 (amendments accepted, applied by WP-6); PAT-ARCH-014 unchanged; no new pattern.
- **Non-goals:** `/rule` alias; edit/regenerate or entity marks on side-chat; new `MessageKind`; changing the REST `invoke` path; a frontend test runner; history migration.
