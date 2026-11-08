---
id: SPEC-0019
requirement: REQ-0028
adr: ADR-0013
status: accepted
date: 2026-11-07
---

# SPEC-0019: World memory slice B: mention detection and an approval queue

## 1. Requirement
REQ-0028; restatement in [docs/requirements/LOG.md](../requirements/LOG.md) (not copied). ADR:
[ADR-0013](../adr/0013-world-mention-detection-approval-queue.md) (accepted; D1-D10 cited); pattern
[PAT-ARCH-012](../patterns/architecture/PAT-ARCH-012-post-reply-world-mining.md). Decisions the packages use:
- Beyond the ADR (human sign-off): chat **and** `/narrate` replies are mined (never `/roll /attack /rules /monster`); candidates are campaign-wide (`session_id` NULL, source session in `evidence`); default-on needs the playtest (WP-7, M-1).
- Ladder v5 adds nullable `world_entities.evidence` (JSON TEXT), exposed by the store and `WorldEntityResp` only, never by create/PATCH requests.
- `app/intelligence/world_mentions.py` is pure stdlib; `app/services/world_mining.py` does store I/O; the worker calls it fail-soft after `job.completed`. Settings `world.detect_mentions` (true), `world.max_candidates_per_reply` (3, `ge=0`; 0 = match only). No second model call, new route or frontend (REQ-0029).

## 2. Test Spec (written first)
`pytest -q`, **no network, no Ollama**; `:memory:` stores (`session_store`) except file-DB tests in `tmp_path`. Worker tests use `make_stub_service(world_store=session_store, ...)`, `wait_idle` (it also waits for detection) and a stubbed `svc.client.chat`.
Log assertions read `caplog.records` attributes (the JSON formatter drops extras). Gate: `pytest -q`, `ruff check app tests scripts`.
Shared fixture **F1** (tavern reply; paragraphs split by `/`). Every test that mines F1 first holds a canon `Brightwater` entity, so it proposes exactly `Rusty Anchor`, `Old Marta`, `Captain Harl` (without it `Brightwater` ranks first): `You push open the door of the Rusty Anchor and the noise of the tavern washes over you. Behind the bar, Old Marta polishes a mug and nods. "Aria, you came back," she says. "Captain Harl was asking after you."` / `Harl sits in the corner with two sailors from Brightwater. He raises a hand and Marta whispers, "Careful. The Captain owes money to half of Brightwater." Veyra's name is not spoken here.`

### WP-1
Files `tests/test_store_migration.py`, `tests/test_sqlite_store.py`, `tests/test_world_store.py`.
- T-01 `test_fresh_store_has_evidence_column`: `world_entities` has 10 columns incl. `evidence`; `user_version == 5`; a new entity reads `evidence None`.
- T-02 `test_v1_to_v4_files_upgrade` (existing parametrized test plus `_make_v4_db`): row kept, `evidence` NULL, version 5, reopen is a no-op.
- T-03 every ladder-head `4` becomes 5, world column count 9 becomes 10, `test_t05`'s bogus step version 5 becomes 6; `test_pat_arch_008_*` unchanged.
- T-04 `test_entity_evidence_round_trip` (`ENTITY_KEYS` gains `evidence`): `create_entity(evidence=...)` reads back (also on reopen); `update_entity` replaces it and bumps `updated_at`; `None` stores NULL.

### WP-2
Files `tests/test_world_vocab.py`, `tests/test_world_api.py`.
- T-05 `test_detection_settings_defaults`: `WorldSettings()` gives `detect_mentions is True`, `max_candidates_per_reply == 3`; `0` accepted, `-1` raises `ValidationError`; `settings.json` has both keys.
- T-06 `test_entity_resp_exposes_evidence_read_only`: GET one/list return `"evidence": null` for an API-created entity and the dict for one made via `store.create_entity(evidence=...)`; POST and PATCH bodies with `evidence` return 422; `/openapi.json` has `evidence` on `WorldEntityResp` only.

### WP-3
File `tests/test_world_mentions.py`. `detect_mentions(text, known, stoplist=(), max_candidates=3)`; `known` items `{"id","name","aliases"}`; fixtures F1 (above) and F2-F4.
- F1 (known `e-bw` Brightwater, `e-vey` Veyra; stoplist `["Aria"]`) -> `matched_ids == ("e-bw","e-vey")`; candidates `Rusty Anchor` (other), `Old Marta` (other), `Captain Harl` (npc), in that order; with no known entities `Brightwater` (count 2) ranks first.
- F2 dungeon (no known; stoplist `["Aria"]`): `The passage slopes down into the Hollow Crypt. Torchlight catches carved letters above the arch: "Sir Aldren of Vale, who kept the gate, rests here." Dust coats everything.` / `Make a Wisdom check, Aria. A DC 14 Perception check reveals a loose flagstone. Beneath it lies a silver key stamped with the sigil of the Ashen Order. The Order's guards never came this deep.` -> `Hollow Crypt` (other), `Sir Aldren of Vale` (npc), `Ashen Order` (other); `max_candidates=2` keeps the first two.
- F3 rules answer (no known): `Grappling uses an Athletics check against the target's Strength (Athletics) or Dexterity (Acrobatics) check. On a success the target has the Grappled condition and its speed drops to 0.` / `You can end the grapple on your turn. See the Player's Handbook.` -> nothing matched or proposed.
- F4 aliases (known `e-bw` Brightwater alias `Canal City`; `e-marta` "Marta Voss" alias `Old Marta`): `Morning light spills over the Canal City. Old Marta is already at her stall, counting coins, while Mother Greaves watches from across the square.` -> `matched_ids == ("e-bw","e-marta")`, one candidate `Mother Greaves` (other).
- T-10..T-13 `test_fixture_f1`..`f4`: the expectations above; each snippet contains its name and `len <= 160`.
- T-14 `test_known_matching`: casefolded whole-token match of name or alias (`mira` matches "Mira", not "Miranda"); `matched_ids` distinct, first-appearance order.
- T-15 `test_candidate_shapes`: `Tower of the Moon` is one candidate; a 5-word run is dropped; `DC` ignored; a comma splits runs; `'s` stripped.
- T-16 `test_single_word_rules`: a single word seen only sentence-initially is dropped, kept if also seen mid-sentence; `Ox` dropped; `Marta` inside `Old Marta`, and `Voss` inside known `Marta Voss`, dropped.
- T-17 `test_stoplist`: built-ins (pronouns, openers, weekdays, `God`, abilities, skills, conditions) never proposed; `The Rusty Anchor` -> `Rusty Anchor`; `stoplist=["Aria Windfoot"]` drops both words; phrase `Wood Elf` drops `Elf`, `Fire Peak` survives `Fire Giant`.
- T-18 `test_cap_rank_and_kind`: rank by count desc then first position; `max_candidates=0` none; casefold duplicates merged; a title word first (`Lord Lady Sir Captain King Queen Master Mistress Elder Brother Sister`) gives `npc`.
- T-19 `test_snippet_and_purity`: snippet = whole sentence (split on `.!?` plus quotes then space, or newline), whitespace collapsed, at most 160 chars ending `…` when cut; equal input gives equal output; `known` not mutated.

### WP-4
File `tests/test_world_mining.py`; real `:memory:` store; calls `mine_reply(...)` with F1 text.
- T-20 `test_creates_pending_rows`: `status pending`, `session_id None`, `notes ""`, `kind` from the candidate, `evidence` keys exactly `detector ("deterministic"), session_id, source_message_id, snippet, first_seen_at (ISO UTC), message_ids == [reply id]`.
- T-21 `test_pending_mention_bumps_message_ids`: a later reply id is appended once (no duplicates); at 20 ids nothing is appended and `updated_at` is unchanged; a manual pending row (`evidence None`) is untouched.
- T-22 `test_canon_and_rejected_never_written`: both keep `updated_at` and `evidence` when mentioned; a rejected name creates no row.
- T-23 `test_idempotent_on_redetection`: same reply id and text twice: same rows, second call `proposed 0, bumped 0`, `updated_at` equal; `max_candidates=0` proposes nothing but still bumps.
- T-25 `test_catalog_stoplist`: returns the `.name`s under `species/weapons/rules/creatures`; missing keys give `frozenset()`.

### WP-5
File `tests/test_world_detection_worker.py`; chat stub returns F1 text; `caplog` on `app.services.inference_service`.
- T-30 `test_chat_reply_creates_pending_candidates`: three pending rows with the reply id in `evidence.message_ids`; user message and reply `completed` (a patched `mine_reply` sees the user message already `completed`); the `world.detected` record has int `matched, proposed, bumped, duration_ms`, no name or snippet, and follows `job.completed`.
- T-32 `test_tools_other_than_narrate_not_mined`: stub `tool_service` (see `tests/test_slash_dispatch.py`) returning F1 text: `meta.tool roll` makes no row and no `world.detected`; `narrate` makes rows.
- T-33 `test_skipped_cases`: `world_store=None`, `detect_mentions=False` and a `canon False` reply (regenerate after `correct_message(canon=False)`) each make no row and raise nothing.
- T-34 `test_detection_failure_is_fail_soft`: store whose `list_entities` raises: user message `completed`, reply kept, one WARNING `world.detect_failed`, no `job.failed`.
- T-35 `test_regenerate_in_place`: same text adds no rows or ids; new text with a new name adds one row.
- T-36 `test_character_and_catalog_names_not_proposed`: character "Aria" never proposed; `make_stub_service(mention_stoplist=["Goblin"])` drops `Goblin`; `build_services(...)["inference"]._mention_stoplist` holds species names (shut it down).

### WP-6
File `tests/test_world_detection_api.py`; `create_app(services={"inference": svc, "session": store, "world": store})`, `TestClient`, `AUTH`; POST `/api/v1/sessions/{id}/messages`; assert on the recorded system message only.
- T-40 `test_chat_reply_shows_in_pending_queue`: `GET /api/v1/world/entities?status=pending` lists the candidates (`session_id null`, `evidence.source_message_id == reply id`); `status=canon` lists none.
- T-41 `test_pending_not_injected_until_approved`: next prompt's system content lacks `Rusty Anchor`; after `PATCH {"status":"canon","kind":"place"}` the following one contains it.
- T-42 `test_rejected_never_reproposed`: `PATCH {"status":"rejected"}` on `Old Marta`, then another mentioning reply: no new row; after `DELETE` a third mention proposes it again.

### WP-7
File `tests/test_detect_replay.py` (loads the script with `importlib.util`, as `tests/test_sync_open5e.py`).
- T-50 `test_replay_prints_candidates_and_counts`: `tmp_path` DB from `SqliteSessionStore` (character Aria; canon chat reply with F1 text, `meta.tool roll` reply, `canon False` reply; closed): `main([path])` returns 0; stdout has each candidate with its snippet, per-reply counts and a summary (replies scanned, candidates, mean, max per reply); only the canon chat reply is scanned.
- T-51 `test_replay_is_read_only`: file sha256 and `user_version` unchanged; no `world_entities` rows.
- T-52 `test_replay_older_schema_and_refusals`: a v1 DB (no `canon`, no `world_entities`) works; a missing path and the repo-root `dnd.db` return 2 (the latter never opened).
- M-1 manual acceptance (human, not CI): `cp dnd.db /tmp/dnd-copy.db`; `python -m scripts.detect_replay /tmp/dnd-copy.db`; label each candidate real or not. Default-on stays only if real >= 50% and mean <= 1.5 candidates per scanned reply; else tune the stoplist or cap, add a regression case to `tests/test_world_mentions.py`, re-run.

## 3. Work Packages

### WP-1: Ladder v5 `evidence` column and store support
- **Files:** `app/services/repos.py`, `app/type_defs.py`, `tests/test_store_migration.py`, `tests/test_sqlite_store.py`, `tests/test_world_store.py`
- **Inputs:** ladder head v4 in `_MIGRATIONS` (append-only); `_entity_from_row`, `create_entity`, `update_entity`, `_ENTITY_EDITABLE`; `WorldStore` Protocol.
- **Outputs:** `(5, "world_entities", "evidence", "ALTER TABLE world_entities ADD COLUMN evidence TEXT")`; entity dicts carry `evidence` (`json.loads`, `None` for NULL); `create_entity(..., evidence: dict | None = None)`; `"evidence"` joins `_ENTITY_EDITABLE` and `update_entity` JSON-dumps it (`None` -> NULL); the Protocol gains `evidence`; old tests updated (T-03).
- **Acceptance criteria:** T-01..T-04 pass; nothing else changes; the step stays additive (`test_pat_arch_008_*` unchanged).
- **Patterns used/created:** PAT-ARCH-008, PAT-ARCH-002.

### WP-2: API response field and settings
- **Files:** `app/schemas/world.py`, `app/config.py`, `settings.json`, `tests/test_world_vocab.py`, `tests/test_world_api.py`
- **Inputs:** WP-1 entity dicts carry `evidence`; the request models use `extra="forbid"`.
- **Outputs:** `WorldEntityResp.evidence: dict[str, Any] | None = None`; request models unchanged; `WorldSettings.detect_mentions: bool = True`, `max_candidates_per_reply: int = Field(default=3, ge=0)`; both keys in `settings.json` `world`.
- **Acceptance criteria:** T-05, T-06 pass; existing world tests stay green.
- **Patterns used/created:** PAT-ARCH-005.

### WP-3: Pure mention detector
- **Files:** `app/intelligence/world_mentions.py` (new), `tests/test_world_mentions.py` (new)
- **Inputs:** stdlib only (`re`, `dataclasses`); no `app.services`, store, client, `app.deps` (enforced by `test_pat_arch_012_*`).
- **Outputs:** frozen `Candidate(name, kind, snippet, count)` and `Detection(matched_ids: tuple[str, ...], candidates: tuple[Candidate, ...])`; `detect_mentions(text: str, known: Sequence[Mapping], stoplist: Iterable[str] = (), max_candidates: int = 3) -> Detection`; module constants for the built-in stop words and title words.
- **Acceptance criteria:** T-10..T-19 pass and `test_pat_arch_012_*` stays green. Rules: (1) tokens are `[a-z0-9]+` of the casefolded text; a known entity matches when the token tuple of its name or any alias occurs contiguously (caller passes all statuses). (2) A word is `[A-Za-z]+(?:['’-][A-Za-z]+)*`, uppercase-initial, not ALL-CAPS; a run is 1-4 words joined by single spaces, lowercase `of`/`the` allowed between capitalised words; punctuation ends a run; longer runs dropped; trailing `'s` stripped from the last word. (3) Leading stop words (built-in or caller) are trimmed; built-ins: pronouns, sentence openers (`The And But Then As When There Behind ...`), weekdays, `God`/`Gods`, abilities, skills, conditions, phrases `Player's Handbook`, `Dungeon Master`, `Monster Manual`. (4) Caller `stoplist` strings are tokenised; a candidate is dropped when its token tuple lies contiguously inside any stop phrase, known name or known alias. (5) A single word needs 3+ chars, one non-sentence-initial occurrence (sentence start = text start, after `.!?` or a newline, optionally behind quotes or markdown marks, or an opening quote after `,` or `:`) and must not lie inside another accepted candidate. (6) `count` = occurrences of the exact token tuple; dedupe on it; rank by count desc then first position; keep `max_candidates` (0 = none; matching still runs). (7) `kind` is `npc` if the first word is a title word, else `other`. (8) Snippet per T-19.
- **Patterns used/created:** PAT-ARCH-012 rules 4-5.

### WP-4: Apply detection to the world store
- **Files:** `app/services/world_mining.py` (new), `tests/test_world_mining.py` (new)
- **Inputs:** WP-1 store methods; WP-3 `detect_mentions`; any `WorldStore`.
- **Outputs:** `mine_reply(world_store, *, session_id, reply_id, text, stoplist=(), max_candidates=3) -> dict[str, int]` (`matched, proposed, bumped`) and `catalog_stoplist(reference: Mapping) -> frozenset[str]` (`.name` of every entry in `species`, `weapons`, `rules`, `creatures`; missing keys ignored). `mine_reply` reads `list_entities(session_id)` (all statuses), runs the detector, then: a matched `pending` entity with non-None `evidence` gets `reply_id` appended to `evidence.message_ids` when absent and under 20 (one `update_entity` only if changed); each candidate becomes `create_entity(name, kind, status="pending", session_id=None, evidence={detector:"deterministic", session_id, source_message_id: reply_id, snippet, first_seen_at: aware-UTC ISO, message_ids:[reply_id]})`. Never writes canon or rejected rows, never deletes.
- **Acceptance criteria:** T-20..T-23, T-25 pass; a repeat call with the same reply id and text writes nothing; exceptions propagate (the worker owns the try/except).
- **Patterns used/created:** PAT-ARCH-012 rule 5, PAT-ARCH-010.

### WP-5: Worker hook `_detect_mentions`
- **Files:** `app/services/inference_service.py`, `app/services/build_services.py`, `tests/test_world_detection_worker.py` (new)
- **Inputs:** `_worker_loop` (`job.completed` log ends the `try`; both branches call `_append_reply`, which returns the reply id); `_inject_world` (fail-soft precedent); WP-4 `mine_reply`, `catalog_stoplist`; WP-2 settings.
- **Outputs:** constructor kwarg `mention_stoplist: Iterable[str] | None = None` (kept as `self._mention_stoplist`); `self._detect`, `self._max_candidates` from `settings.world`; after the `job.completed` log the worker calls `self._detect_mentions(job, reply_id, text)` for chat and `narrate` jobs only; `build_services` passes `mention_stoplist=catalog_stoplist(reference)`. `_detect_mentions` returns at once when `self._world_store is None`, the switch is off, or `job.store.get_message(...)` shows the reply `canon` False; else it adds the session character's name (`job.store.get_character`, may be None) to the stoplist, calls `mine_reply(self._world_store, ...)` and logs INFO `world.detected` (`session_id, message_id, reply_id, matched, proposed, bumped, duration_ms`; counts only). Its own `try/except Exception` logs WARNING `world.detect_failed` (`session_id, message_id, error`) and never touches message status.
- **Acceptance criteria:** T-30, T-32..T-36 pass; existing worker, injection and regenerate tests stay green; no new thread, route or model call.
- **Patterns used/created:** PAT-ARCH-012 rules 1-3, 6; PAT-ARCH-010.

### WP-6: REST plus worker integration tests
- **Files:** `tests/test_world_detection_api.py` (new); app code only to fix a defect a test exposes in WP-1..5.
- **Inputs:** WP-1..5 done; setup as in `tests/test_slash_dispatch.py` and `tests/test_world_api.py`.
- **Outputs:** the three tests above (F1 text as the stubbed reply, varied where a later reply must differ).
- **Acceptance criteria:** T-40..T-42 pass; approval uses only the existing PATCH.
- **Patterns used/created:** PAT-ARCH-005, PAT-ARCH-012.

### WP-7: Replay script and playtest gate
- **Files:** `scripts/detect_replay.py` (new), `tests/test_detect_replay.py` (new)
- **Inputs:** WP-3 `detect_mentions`; WP-4 `catalog_stoplist` and the reference loaders `build_services` uses.
- **Outputs:** `main(argv: list[str] | None = None) -> int` (`PATH`, optional `--max-candidates N`) and `replay(path, ...) -> list[dict]`. Read-only: `sqlite3.connect("file:<abs>?mode=ro", uri=True)` plus `PRAGMA query_only = ON` (not `SqliteSessionStore`, which migrates); a missing path or the repo-root `dnd.db` prints a reason and returns 2. Scans, in `seq` order, completed canon assistant messages (`canon` NULL/1 or no such column) with `meta.tool` absent or `narrate`; known entities are `world_entities` rows (none if the table is absent) plus candidates proposed earlier in the run; stoplist = catalog names plus the session character name. Prints per matching reply the counts and `+ name [kind] "snippet"` lines, then the summary and the M-1 rule.
- **Acceptance criteria:** T-50..T-52 pass; M-1 is recorded in the PR description before default-on is accepted; the script never opens `dnd.db`.
- **Patterns used/created:** PAT-ARCH-012 rule 6.

## 4. Other Details
- **Risks:** heuristic false positives (playtest gate); the JSON log formatter drops extras, so `world.detected` is not visible in emitted logs yet; duplicate row if the operator creates the same name mid-detection (accepted, ADR-0013).
- **Rollback plan:** set `world.detect_mentions` false or delete the one `_detect_mentions` call; v5 is additive and harmless unread; never lower `user_version`.
- **Patterns applied/created:** PAT-ARCH-012, 010, 008, 005, 002 (accepted); none created.
- **Non-goals:** frontend queue UI and bulk approve (REQ-0029); LLM extraction (REQ-0030); mining other slash tools or edited text; quoted-name or coreference rules; WS event or new route; fixing the log formatter.
