---
id: SPEC-0014
requirement: REQ-0024
adr: ADR-0009
status: implemented
date: 2026-11-01
---

# SPEC-0014: `/rules` consult tool (keyword selection over the in-memory SRD rules catalog)

## 1. Requirement

Restated in [docs/requirements/LOG.md](../requirements/LOG.md) as REQ-0024. Linked ADR:
[ADR-0009](../adr/0009-rules-consult-tool.md) (status `proposed`, option A chosen).

Verbatim restatement:

> The DM MUST be able to ask a rules question with a slash tool (`/rules <question>`; name proposed, to be confirmed) whose reply MUST NOT use the narrator voice (`build_narrator_prompt` MUST NOT be used; a pure rules-consult prompt builder per PAT-ARCH-003 MUST be used instead). The tool MUST answer from the in-memory reference catalog of SRD rules (open5e `rules`, SRD 5.1 `srd-2014` and SRD 5.2 `srd-2024` documents only), loaded once at startup per PAT-ARCH-006, by selecting the rule entries relevant to the question and placing their text in the prompt within a bounded character budget held in settings. The tool MUST NOT read `dnd_data/` or call open5e at runtime. If no relevant rule is found, the catalog is empty, or the relevant text would exceed the budget, the tool MUST answer from model training data and MUST set `meta.source` to `training` (otherwise `rules`, with the rule ids used in `meta`); the reply SHOULD state that it is not checked against the rules text. Empty input MUST raise `ToolError`; the tool MUST follow the tool contract in `.github/instructions/tools.instructions.md`, MUST NOT write messages, MUST NOT log prompts, and tests MUST run without network or Ollama. `/narrate`, `/roll`, the `/attack` work (REQ-0022) and the reference routes (REQ-0018, REQ-0019) MUST NOT change under this requirement.

Decisions carried in from ADR-0009 (all defaults, none accepted yet; see section 4 "Open questions"):
- Option A: deterministic keyword selection inside the tool, exactly one `generate` call per question.
- New dataset `app/reference/rules.json`, built by `scripts/ingest_open5e.py`, SRD 5.1 and 5.2 only, loaded with the existing `load_entries`.
- New setting `prompts.rules_budget_chars` (default 6000, minimum 0).
- `meta = {"tool": "rules", "source": "rules" | "training", "rule_ids": [...]}`; `rule_ids` is always present and is `[]` in training mode.
- **No read-only route** for the rules dataset in this spec (ADR-0009 decision 3: out of scope; REQ-0024 freezes the reference routes).

Verified facts used by this spec (read from the tree on 2026-11-01):

| # | Fact | Where verified |
|---|---|---|
| V1 | A tool module needs `NAME: str` and callable `run`; a module with neither is skipped by discovery (so a helper-only module is harmless) | `app/intelligence/tools/__init__.py` lines 45-50 |
| V2 | `narrate.run` strips args, raises `ToolError(_USAGE)` if empty, calls `context["inference"].generate(prompt)` once, returns `{"text", "meta": {"tool": NAME}}`, imports `get_settings` from `app.config` | `app/intelligence/tools/narrate.py` |
| V3 | `roll.py` imports `ToolError` from `app.intelligence.tools` and returns `{"text","meta"}` | `app/intelligence/tools/roll.py` |
| V4 | `load_entries(path, model, dataset, logger=...)` never raises; missing file logs `reference.unavailable` with `reason="missing"` and returns `[]`; drops invalid and duplicate-id entries with `reference.entry_dropped` | `app/reference/loader.py` |
| V5 | `Weapon` is the precedent for an open5e model: `extra="forbid"`, `id` pattern `^[a-z0-9]+(-[a-z0-9]+)*$`, `edition: Literal["5e","5.5e"] \| None`, `source`, `publisher: str \| None`, `third_party: bool`, `source_key`, plus a `WEAPONS_PATH` constant, no loader function | `app/reference/weapons.py` |
| V6 | `build_services` builds `reference = {"species": ..., "weapons": load_entries(WEAPONS_PATH, Weapon, "weapons")}` then sets `tool_service.default_context["reference"] = reference` | `app/services/build_services.py` lines 33-41 |
| V7 | `ToolService.invoke` drops client context keys that are in `SERVER_CONTEXT_KEYS` **or in `default_context`**. `reference` is not in `SERVER_CONTEXT_KEYS` (`tools.instructions.md` and `tool_service.py` line 47 do not list it) but is protected because `build_services` puts it in `default_context` | `app/services/tool_service.py` lines 46-48, 129-136 |
| V8 | `PromptSettings` currently holds `enable_narration`, `enable_adjudication`, `verbosity_default`, `dm_voice`; `settings.json` `prompts` block has the same keys; `get_settings()` reads `settings.json` from the cwd and is `lru_cache`d | `app/config.py` lines 56-61, `settings.json` |
| V9 | `ingest_open5e.py`: `DOCUMENT_ALLOWLIST` and `PROJECTION` are per-dataset dicts, `CONSUMERS` gates ingest (`ingest` raises if the dataset is not a key), `_flatten` reads `raw["document"]["key"]`, `doc["display_name"]`, `doc["publisher"]["name"]`, and `_description` reads `raw["descriptions"][]`; `filter_allowlisted` reads `e["document"]["key"]`; `_id_candidates` gives `[slug]` for srd-2024 and `[slug, slug-5e]` for srd-2014; `_assign_ids` raises `no free id for ...` when every candidate is claimed; `ingest` loads `_documents.json` after `build_records` and warns if absent | `scripts/ingest_open5e.py` lines 27-68, 84-129, 137-178, 313-345 (as read) |
| V10 | Raw `dnd_data/rules.json` entries (first entries read) have exactly: `key`, `name`, `desc`, `index`, `initialHeaderLevel`, `document` (a **plain string**, e.g. `"srd-2024"`), `ruleset`, `crossreferences`. No `descriptions[]`, no `gamesystem`. `desc` is markdown text with `\n\n` and tables. The file is one 352 KB line | `dnd_data/rules.json` line 1 (read) |
| V11 | `tests/test_reference_budget.py` parametrizes over `REFERENCE_DIR.glob("*.json")` for the 2,000,000-byte / 2,000-entry check, and over `OPEN5E_MODELS` (currently only `weapons`) for the no-dropped-entry check | `tests/test_reference_budget.py` lines 22-56 |
| V12 | `app/reference/ATTRIBUTION.md` already has sections for `srd-2014` (CC-BY 4.0; OGL 1.0a) and `srd-2024` (CC-BY 4.0); `LICENSE-OGL.txt` is committed | `app/reference/ATTRIBUTION.md`, `app/reference/` listing |
| V13 | `detect_tool` accepts any `/name args` via `TOOL_RE`; the worker dispatches it (PAT-ARCH-004); `tests/test_slash_dispatch.py` has a `slash_env` fixture whose `svc.client.chat` is stubbed and whose `ToolService` default context has `inference` but **no `reference`** | `app/intelligence/tool_handler.py` line 28; `tests/test_slash_dispatch.py` lines 43-62 |
| V14 | `tests/test_tool_calling.py` has a `FakeInference` (records prompts, returns a fixed reply) and asserts discovery with `ToolService(discover_on_init=True).list_tools()`; `test_build_services_wires_tool_service_into_inference` asserts only the top-level services keys (`session, tool, inference, reference`), not the keys of `reference` | `tests/test_tool_calling.py` lines 23-31, 259-276, 377-387 |
| V15 | `.gitignore` lists `dnd_data/` (line 29), so `dnd_data/rules.json` is absent in CI and on a fresh clone | `.gitignore` |
| V16 | `build_narrator_prompt` and `DM_ROLE_PROMPT` live in `app/intelligence/prompt_builders.py`; the module imports `PromptSettings` from `app.config`, uses `from __future__ import annotations` and its own `logger = get_logger(__name__)` | `app/intelligence/prompt_builders.py` lines 18-34 |

Facts taken from ADR-0009 and **not re-measured** (the spec writer had no execution tool): 283 raw `rules` entries (227 `srd-2014`, 56 `srd-2024`), about 297,000 chars of `desc`, about 300-400 KB projected. WP-5 measures and reports these.

## 2. Test Spec (written first)

42 tests. All run with `pytest -q`, need **no network and no Ollama**: `inference.generate` is always a stub (`FakeInference`-style object that records the prompt and returns a fixed string, or the `slash_env` stubbed `client.chat`), and the rules catalog is always a list of in-memory `Rule` objects built inline, except where a test is explicitly about the committed `app/reference/rules.json` (T-24 to T-28). Tests that exercise the committed file read `app/reference/rules.json` only, never `dnd_data/`. Ingest tests build their inputs under `tmp_path`.

The gate for every WP is `pytest -q`, `ruff check app tests scripts`, and `black --check app tests scripts`.

Conventions: each test is a plain `def test_...` function; put its T-id in a comment on the line above (as `tests/test_slash_dispatch.py` does). `Rule` fixtures use a small helper `_rule(id, name, description, edition="5.5e")` that fills `source="SRD"`, `publisher="Wizards of the Coast"`, `third_party=False`, `source_key=f"srd_{id}"`.

### WP-1: setting (`tests/test_rules_settings.py`)

| ID | Test | Expected |
|----|------|----------|
| T-01 | `PromptSettings().rules_budget_chars` | equals `6000` (int) |
| T-02 | bounds | `PromptSettings(rules_budget_chars=0).rules_budget_chars == 0`; `PromptSettings(rules_budget_chars=-1)` raises `pydantic.ValidationError` |
| T-03 | `settings.json` at the repo root (read with `json.loads` from `ROOT / "settings.json"`) | `data["prompts"]["rules_budget_chars"] == 6000`, and `Settings(**data).prompts.rules_budget_chars == 6000` |

### WP-2: selection (`tests/test_rules_selection.py`; imports `select_rules` from `app.intelligence.tools.rules` and `Rule` from `app.reference.rules`)

| ID | Test | Expected |
|----|------|----------|
| T-04 | name match outranks description match | Catalog listed as `[B, A]`: A (`name="Opportunity Attack"`, description `"A creature leaves your reach."`), B (`name="Reactions"`, description `"An opportunity attack is a reaction. Opportunity attack rules: attack when a creature leaves."`). Question `"opportunity attack leaves"` has tokens `{opportunity, attack, leave}`. A scores 3x2 name hits + 1 text hit = 7; B scores 0 name hits + 3 text hits = 3 (still relevant). Result is `[A, B]` (A first although it is later in the catalog). |
| T-05 | description-only relevance needs 3 distinct matches | Entry X (`name="Notes"`, description `"A creature that leaves your reach can be hit."`). Question `"creature reach"` (2 distinct description matches) returns `[]`. Question `"creature leaves reach"` (3 distinct matches) returns `[X]`. |
| T-06 | tokenizing: stopwords, punctuation, case, plural folding | Entry E (`name="Opportunity Attack"`, any description without the word "use"). `"What are the rules?"` returns `[]` (every token is a stopword). `"Can I use Opportunity Attacks?"`, `"opportunity-attack!!"` and `"OPPORTUNITY ATTACKS"` each return `[E]`. |
| T-07 | edition tie-break | Two entries with different names but equal score for the question, one `edition="5e"` and one `edition="5.5e"`: the `5.5e` entry is first. Two entries with equal score and equal edition are ordered by `id` ascending. |
| T-08 | same rule in both editions keeps one | Entries `cover-5e` (`edition="5e"`, name `"Cover"`) and `cover` (`edition="5.5e"`, name `"Cover"`, identical description). Question `"cover"`. Result is exactly `[cover]` (one entry, the `5.5e` one). Also with names differing only in case/punctuation (`"Cover"` vs `"cover."`) only one is kept. |
| T-09 | at most 3 entries | Five distinct relevant entries (all short, budget large, e.g. `100000`). Result has length 3 and is the top 3 by (score desc, edition rank, id). |
| T-10 | never truncate; skip what does not fit | Relevant ranked entries R1 (400 chars), R2 (500 chars), R3 (100 chars), budget `600`. Result is `[R1, R3]`; each returned entry's `description` is the original string (same length, not cut). |
| T-11 | best match too big means training | Ranked R1 (700 chars), R2 (200 chars), budget `600`. Result is `[]` even though R2 would fit. |
| T-12 | training-mode inputs | `select_rules(q, [], 6000) == []`; budget `0` returns `[]` for a catalog with a perfect match; a question with no usable tokens returns `[]`; budget `-5` returns `[]`. |
| T-13 | purity | Calling twice with the same arguments returns equal lists; the input list and `Rule` objects are not mutated (list order and `model_dump()` unchanged); returned items are the same objects as in the input list; the module-level function does no I/O (called with `monkeypatch` making `builtins.open` raise, it still works). |

### WP-3: prompt builder (`tests/test_rules_prompt.py`; imports `build_rules_prompt`, `DM_ROLE_PROMPT` from `app.intelligence.prompt_builders`)

| ID | Test | Expected |
|----|------|----------|
| T-14 | grounded order | With two excerpts `{"name": "Cover", "edition": "5.5e", "text": "TEXT-ONE"}` and `{"name": "Hiding", "edition": "5e", "text": "TEXT-TWO"}` and question `"Does cover stack?"`: returns a `str`; `index("TEXT-ONE") < index("TEXT-TWO") < index("QUESTION: Does cover stack?") < index("DIRECTIVES:")`; contains `"[1] Cover (SRD 5.2 (2024))"` and `"[2] Hiding (SRD 5.1 (2014))"`. |
| T-15 | training prompt | With `[]` excerpts: contains the question, `"DIRECTIVES:"` and `"general knowledge"`; does not contain `"RULES EXCERPTS"` or `"[1]"`; `index(question) < index("DIRECTIVES:")`. |
| T-16 | no narrator voice | For both the grounded and the training prompt: none of `DM_ROLE_PROMPT`, `"SYS:"`, `"VOICE:"`, `"TONE:"`, `"PERSONA:"`, `"Dungeon Master"` is in the string. `inspect.getsource(build_rules_prompt)` contains neither `"NarratorVoiceParams"` nor `"DM_ROLE_PROMPT"` nor `"build_narrator_prompt"`. |
| T-17 | pure and verbatim | The excerpt dicts and the list are not mutated; two calls return equal strings; an excerpt text containing `"\n\n## Heading\n\n\|a\|b\|\n\|---\|---\|"` appears unchanged in the prompt; a question with surrounding whitespace is stripped (`"QUESTION: x"`, not `"QUESTION:  x "`); an edition other than `"5e"`/`"5.5e"` (including `None`) renders as `"(edition unknown)"`. |

### WP-4: ingest support for `rules` (`tests/test_ingest_rules.py`; loads `scripts/ingest_open5e.py` with `importlib.util` exactly as `tests/test_ingest_open5e.py` does; every test uses a fixture that monkeypatches `ingest_open5e.OVERLAY_DIR` to `tmp_path / "no-overlays"` and `ingest_open5e.OGL_LICENSE_SOURCE` to a nonexistent `tmp_path` path)

Raw fixture helper: `_raw_rule(name, document_key, key=None, desc="desc")` returns `{"key": key or f"{document_key}_{slug}", "name": name, "desc": desc, "index": 1, "initialHeaderLevel": 2, "document": document_key, "ruleset": f"{document_key}_x", "crossreferences": {"to": []}}` (note `document` is a **string**). Documents fixture: `{"srd-2014": {...}, "srd-2024": {...}, "a5e-ag": {...}}` shaped like `_documents.json` records (`key`, `display_name`, `publisher: {"name": ...}`, `permalink`, `licenses: [{"name": "Creative Commons Attribution 4.0", "key": "cc-by-40"}]` so no OGL file is needed).

| ID | Test | Expected |
|----|------|----------|
| T-18 | `resolve_documents(entries, documents)` | A string `document` is replaced by a copy of `documents[key]`; the input list/entries are not mutated; an entry whose `document` is already a dict passes through unchanged; an unknown key raises `ValueError` whose message contains the unknown key and the entry key. |
| T-19 | projection, verbatim text, mappings | `build_records("rules", resolve_documents([...], documents))` for one `srd-2024` and one `srd-2014` entry: each record's key set equals `set(ingest_open5e.PROJECTION["rules"])` which is exactly `{id, name, edition, source, publisher, third_party, source_key, description}`; `description == raw["desc"]` for a `desc` containing `"\n\n## H\n\n\|a\|b\|"` and a non-ASCII `"–"` (verbatim); `source_key == raw["key"]`; `source == documents[key]["display_name"]`; `publisher == documents[key]["publisher"]["name"]`; `edition` is `"5.5e"` for `srd-2024` and `"5e"` for `srd-2014`; `third_party is False`; none of `desc, index, initialHeaderLevel, ruleset, crossreferences, document, key, slug, document_key, id_fallbacks` is in a record. |
| T-20 | allowlist and consumer | `ingest_open5e.DOCUMENT_ALLOWLIST["rules"] == ["srd-2014", "srd-2024"]`; `"rules" in ingest_open5e.CONSUMERS` and its value contains `"/rules"`; a resolved `a5e-ag` entry is dropped (only SRD entries remain in `build_records` output). |
| T-21 | duplicate names in one document do not raise | Resolved entries: `srd-2024` "Cover" (key `srd-2024_a_cover`), `srd-2014` "Cover" (key `srd-2014_a_cover`), `srd-2014` "Cover" (key `srd-2014_b_cover`). `build_records("rules", ...)` does not raise; ids are `cover` (2024), `cover-5e` (first 2014 in input order) and `srd-2014-b-cover` (second 2014, `_slug(source_key)`); all ids match `^[a-z0-9]+(-[a-z0-9]+)*$` and are unique. |
| T-22 | end-to-end ingest into `tmp_path` | With a snapshot dir holding `_documents.json` and `rules.json` (string `document`s, SRD only, CC licences) and `out = tmp_path/"reference"/"rules.json"`: `ingest("rules", snap, out)` returns the entry count; `load_entries(out, Rule, "rules")` returns that many entries with no warning logged; running `ingest` a second time leaves `out` byte-identical (ids reserved by `source_key`); `ATTRIBUTION.md` exists next to `out` and has a section for each used SRD document. |
| T-23 | guards | `ingest("rules", snap, out)` with no `_documents.json` in `snap` raises `ValueError` (message mentions `_documents.json`) and writes nothing; and for the existing dataset the shared rule is not weakened: two `weapons` entries with the same name in the same `srd-2014` document still raise `ValueError` matching `no free id` through `build_records("weapons", ...)`. |

### WP-5: committed dataset and budget (`tests/test_reference_budget.py` edited; new `tests/test_rules_dataset.py`)

| ID | Test | Expected |
|----|------|----------|
| T-24 | `rules.json` is committed and within budget (in `tests/test_reference_budget.py`) | `"rules.json"` is among the globbed `REFERENCE_FILES` names; `path.stat().st_size <= 2_000_000`; entry count is `>= 1` and `<= 2_000`. |
| T-25 | no dropped entries | `OPEN5E_MODELS` gains `"rules": ("app.reference.rules", "Rule")`, so the existing parametrized `test_t25_open5e_file_drops_no_entries` runs for `rules`: `load_entries(rules.json, Rule, "rules")` returns as many entries as the raw array and logs no WARNING. |
| T-26 | committed dataset shape (in `tests/test_rules_dataset.py`) | Reading `app/reference/rules.json`: every record's key set equals the `Rule` fields; every `edition` is `"5e"` or `"5.5e"` and both appear; every `third_party` is `False`; `id`s are unique; `source_key`s are unique and every one starts with `"srd-2014_"` or `"srd-2024_"`; every `description` is a `str`; the `source` values are exactly the `display_name`s of the two SRD documents as they appear in `app/reference/ATTRIBUTION.md` (`"5e 2014 Rules"`, `"5e 2024 Rules"`). |

### WP-6: startup load (`tests/test_rules_wiring.py`; build services as `tests/test_reference_wiring.py` does and shut the inference service down in `finally` with `asyncio.run(services["inference"].shutdown())`)

| ID | Test | Expected |
|----|------|----------|
| T-27 | catalog is loaded once at startup | `build_services(make_default_repos(), enable_tool_discovery=False)["reference"]["rules"]` is a list of `Rule` with the same length as the raw array in `app/reference/rules.json`; `services["tool"].default_context["reference"] is services["reference"]`; `reference["species"]` and `reference["weapons"]` are still present and non-empty. |
| T-28 | fail-soft | With `monkeypatch.setattr("app.services.build_services.RULES_PATH", tmp_path / "missing.json")`: `build_services(...)` does not raise, `reference["rules"] == []`, exactly one WARNING `reference.unavailable` is logged with `dataset == "rules"` and `reason == "missing"`, and species and weapons still load. |

### WP-7: tool module (`tests/test_rules_tool.py`)

Shared fixtures in the file: `FakeInference` (records `prompts`, `generate(prompt)` returns `"MODEL REPLY"`); `_ctx(catalog=..., inference=fake)` returns `{"inference": fake, "reference": {"rules": catalog}}`; `set_budget(monkeypatch, n)` does `monkeypatch.setattr(rules_tool, "get_settings", lambda: Settings(prompts=PromptSettings(rules_budget_chars=n)))`. Default catalog: `opportunity-attacks` ("Opportunity Attacks", `5.5e`, a 120-char description), `cover` ("Cover", `5.5e`, a 150-char description), `cover-5e` ("Cover", `5e`, same description as `cover`). Default budget in these tests: 6000.

| ID | Test | Expected |
|----|------|----------|
| T-29 | contract and empty input | `rules_tool.NAME == "rules"` and `callable(rules_tool.run)`; for each of `""`, `"   "`, `"\n\t "` `run(arg, ctx)` raises `ToolError` whose message is exactly `"Usage: /rules <your rules question>"`; `fake.prompts == []`. |
| T-30 | grounded answer | `run("  Can I use an Opportunity Attack?  ", ctx)` returns exactly `{"text": "MODEL REPLY", "meta": {"tool": "rules", "source": "rules", "rule_ids": ["opportunity-attacks"]}}`; `fake.prompts` has length 1 and equals `build_rules_prompt("Can I use an Opportunity Attack?", [{"name": "Opportunity Attacks", "edition": "5.5e", "text": <its description>}])`; the prompt contains the rule description; the reply text has no disclaimer appended. |
| T-31 | nothing relevant means training | Question `"what is the airspeed of a swallow"`: result text is `"MODEL REPLY\n\n" + rules_tool.TRAINING_DISCLAIMER` where `TRAINING_DISCLAIMER == "Not checked against the SRD rules text."`; `meta == {"tool": "rules", "source": "training", "rule_ids": []}`; `fake.prompts == [build_rules_prompt("what is the airspeed of a swallow", [])]`; one `generate` call. |
| T-32 | catalog missing or empty means training, not an error | Contexts `{"inference": fake}`, `{"inference": fake, "reference": {}}`, `{"inference": fake, "reference": {"rules": []}}`, `{"inference": fake, "reference": {"rules": None}}`: each returns `source == "training"`, `rule_ids == []`, disclaimer appended, and the training prompt. |
| T-33 | budget cases mean training | With budget `0` and a perfect match: training. With budget `100` and the best match (`opportunity-attacks`, 120 chars) too big: training, and the prompt does not contain the rule description; `rule_ids == []`. With budget `6000` the same question is grounded (control). |
| T-34 | both editions, one id | Question `"cover"` with the default catalog (both `cover` and `cover-5e` present): `meta["rule_ids"] == ["cover"]`, and the prompt contains the cover description exactly once. |
| T-35 | no narrator voice | With `monkeypatch.setattr(prompt_builders, "build_narrator_prompt", boom)` where `boom` raises `AssertionError`, a grounded run and a training run still succeed; the prompt passed to `generate` contains none of `DM_ROLE_PROMPT`, `"VOICE:"`, `"SYS:"`; `not hasattr(rules_tool, "build_narrator_prompt")`. |
| T-36 | meta shape, no store, errors propagate | Context includes `"store"` set to an object whose `__getattr__` raises `AssertionError`: the run succeeds (the tool never touches the store). `set(result["meta"]) == {"tool", "source", "rule_ids"}` (no prompt, no question, no text in meta). A `generate` that raises `IntelligenceError` propagates unchanged. |
| T-37 | logs counts only | Under `caplog.at_level(logging.DEBUG)`, a grounded run with question `"opportunity attack ZZMARKER"` produces exactly one record from logger `app.intelligence.tools.rules`, message `rules.consulted`, with extras `source == "rules"`, `rule_count == 1`, `excerpt_chars == len(description)`; a training run produces one record with `source == "training"`, `rule_count == 0`, `excerpt_chars == 0`. In both runs no log record's message or `__dict__` values contain `"ZZMARKER"`, any rule description text, or any part of the prompt. |
| T-38 | source hygiene | The text of `app/intelligence/tools/rules.py` contains none of `"dnd_data"`, `"open5e"`, `"httpx"`, `".read_text("`, `"open("`, `"build_narrator_prompt"`, `"NarratorVoiceParams"`; the file does not import from `scripts`. The existing `tests/test_reference_budget.py::test_t26_*` tests still pass (no upstream host, no `scripts` import under `app/`). |

### WP-8: discovery, dispatch and docs (`tests/test_tool_calling.py`, `tests/test_slash_dispatch.py`)

| ID | Test | Expected |
|----|------|----------|
| T-39 | discovery (in `tests/test_tool_calling.py`) | `ToolService(discover_on_init=True).list_tools()["rules"] == "app.intelligence.tools.rules"`; `set(get_registry(refresh=True))` still equals `set(ToolService().list_tools())` and contains `"roll"`, `"narrate"` and `"rules"`. |
| T-40 | invoke via `ToolService` (in `tests/test_tool_calling.py`) | `ToolService(default_context={"inference": fake, "reference": {"rules": [rule]}}, discover_on_init=True).invoke("rules", "opportunity attacks", client_context={"reference": {"rules": []}})` returns `meta == {"tool": "rules", "source": "rules", "rule_ids": [rule.id]}`: the client-supplied `reference` is dropped (V7), so the server catalog is used. |
| T-41 | worker dispatch, training (in `tests/test_slash_dispatch.py`, uses `slash_env`) | `_post(slash_env, "/rules what is a bonus action")`; after `wait_idle`: messages are `[user, assistant]`; user `status == "completed"`; assistant `content == "stub reply\n\n" + TRAINING_DISCLAIMER`; assistant `meta == {"tool": "rules", "source": "training", "rule_ids": [], "reply_to": user["id"]}`; `slash_env.chat_calls == [[{"role": "user", "content": build_rules_prompt("what is a bonus action", [])}]]` (no deadlock on `_ollama_lock`, no chat-path call). |
| T-42 | worker dispatch, grounded (in `tests/test_slash_dispatch.py`) | Before posting, `slash_env.ts.default_context["reference"] = {"rules": [<Rule "Opportunity Attacks">]}`; `_post(slash_env, "/rules how do opportunity attacks work")`; after `wait_idle` the assistant `content == "stub reply"` (no disclaimer), `meta == {"tool": "rules", "source": "rules", "rule_ids": ["opportunity-attacks"], "reply_to": user["id"]}`, and the single `chat_calls` prompt contains the rule's description text. |

Not tested by CI (manual, no network needed but needs a live Ollama): the 10-question smoke list in section 4.

## 3. Work Packages

Execute in order. Each package is self-contained: it restates the files, the assumed inputs, the outputs and the full acceptance criteria. The gate for every package is `pytest -q`, `ruff check app tests scripts`, `black --check app tests scripts`. Do not edit `.github/BACKLOG.json` or `docs/requirements/LOG.md`. Do not change `app/intelligence/tools/narrate.py`, `app/intelligence/tools/roll.py`, `app/intelligence/client.py`, `app/services/inference_service.py`, `app/services/tool_service.py`, any `/api/v1/reference/*` route, `app/reference/species.*` or `app/reference/weapons.*`, or the weapons/species JSON files in any WP.

### WP-1: `rules_budget_chars` setting and default
- **Files:**
  - edit `app/config.py` (class `PromptSettings`)
  - edit `settings.json` (the `prompts` object)
  - new `tests/test_rules_settings.py`
- **Inputs:** none beyond the current tree. `PromptSettings` currently has `enable_narration: bool`, `enable_adjudication: bool`, `verbosity_default: str`, `dm_voice: PromptVoiceSettings`, each a `Field(default=...)`. `settings.json` has a `prompts` object with the same keys (`verbosity_default` line is followed by `"dm_voice": {`).
- **Outputs:**
  - `PromptSettings.rules_budget_chars: int = Field(default=6000, ge=0)` (placed after `verbosity_default`, before `dm_voice`).
  - `settings.json` `prompts` gets `"rules_budget_chars": 6000,` so the knob is visible. The JSON must stay valid.
  - Tests T-01 to T-03.
- **Acceptance criteria:**
  - `PromptSettings().rules_budget_chars == 6000` and its type is `int`.
  - `rules_budget_chars=0` is accepted; a negative value raises `pydantic.ValidationError`.
  - `settings.json` parses with `json.loads`, has `prompts.rules_budget_chars == 6000`, and `Settings(**data)` validates.
  - The setting counts only the rules text placed in the prompt (not instructions, not the question). `0` means "always answer from training data". Add a one-line comment above the field saying so.
  - No other setting changes. T-01 to T-03 pass and the gate is green.
- **Patterns used/created:** none (follows the existing `PromptSettings` shape; PAT-ARCH-009 rule 3 names this setting).

### WP-2: `Rule` model and the pure selection function
- **Files:**
  - new `app/reference/rules.py`
  - new `app/intelligence/tools/rules.py` (this WP adds only the helper constants and `select_rules`; **do not add `NAME` or `run` yet** so discovery still skips the module until WP-7)
  - new `tests/test_rules_selection.py`
- **Inputs:** WP-1 is not needed. Precedent: `app/reference/weapons.py` (model) and `app/intelligence/tools/roll.py` (module header style).
- **Outputs:**
  - `app/reference/rules.py`:
    ```
    RULES_PATH = Path(__file__).resolve().parent / "rules.json"
    class Rule(BaseModel):   # model_config = ConfigDict(extra="forbid")
        id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
        name: str
        edition: Literal["5e", "5.5e"] | None
        source: str
        publisher: str | None
        third_party: bool
        source_key: str
        description: str
    ```
    (no loader function; `build_services` calls `load_entries`, as for weapons).
  - `app/intelligence/tools/rules.py` with, exactly:
    - `MAX_RULES = 3`, `NAME_WEIGHT = 3`, `TEXT_WEIGHT = 1`, `MIN_SCORE = 3`.
    - `_EDITION_RANK = {"5.5e": 0, "5e": 1}` (anything else ranks 2). This is the 2014-vs-2024 tie-break and is one constant to flip.
    - `_STOPWORDS`: a `frozenset` of exactly: `a an the and or of to in on at for with from by is are was were be been am do does did can could should would will may might how what when where which who whom why if it its i me my you your he she they them their we us our this that these those as not no any there rule rules work works happen happens also about into than then so just get gets`.
    - `_tokens(text: str) -> set[str]`: lowercase; `re.findall(r"[a-z0-9]+", text.lower())`; drop tokens of length < 2 and tokens in `_STOPWORDS`; then fold each remaining token with `_fold`.
    - `_fold(token)`: if `len(token) > 3` and it ends with `"ies"` return `token[:-3] + "y"`; elif `len(token) > 3` and it ends with `"s"` and not `"ss"` return `token[:-1]`; else return it unchanged. It is applied to the question and to every rule name and description, so both sides fold identically.
    - `_name_key(name) -> str`: `re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()`.
    - `select_rules(question: str, rules: Sequence[Rule], budget_chars: int) -> list[Rule]`, pure and stdlib-only (only `re`, `typing`/`collections.abc`; imports `Rule` from `app.reference.rules` for typing).
  - Tests T-04 to T-13.
- **Acceptance criteria (all must hold; algorithm is normative):**
  1. `q = _tokens(question)`. If `q` is empty, or `rules` is empty, or `budget_chars <= 0`, return `[]`.
  2. For each rule: `name_hits = len(q & _tokens(rule.name))`; `text_hits = len((q - _tokens(rule.name)) & _tokens(rule.description))`; `score = NAME_WEIGHT * name_hits + TEXT_WEIGHT * text_hits`. A rule is **relevant** only if `score >= MIN_SCORE`. So one distinct name match is enough, and a rule matched only in its text needs at least 3 distinct question tokens in its description (2 are not enough).
  3. Sort relevant rules by key `(-score, _EDITION_RANK.get(rule.edition, 2), rule.id)`.
  4. De-duplicate by `_name_key(rule.name)` walking the sorted list: keep the first occurrence of each key, skip the rest (so the same rule in both editions yields one entry; with equal scores `5.5e` wins).
  5. If the deduplicated list is empty, return `[]`. If `len(first.description) > budget_chars` for the first (top) entry, return `[]` (training mode, even if a lower entry would fit).
  6. Pack in rank order: keep a running `used` char total of `len(rule.description)`; for each entry, stop when `MAX_RULES` entries are chosen; **skip** (do not truncate, do not stop) an entry whose description would make `used` exceed `budget_chars`; otherwise add it. Return the chosen `Rule` objects themselves, in rank order, with descriptions untouched.
  7. The function does not mutate its arguments, does no I/O, does not log, and is deterministic.
  8. `app/intelligence/tools/rules.py` imports nothing from `app.config`, `app.services` or any reference loader in this WP, and has no `NAME` and no `run` yet (discovery skips it, V1).
  9. T-04 to T-13 pass and the gate is green.
- **Patterns used/created:** PAT-ARCH-009 (accepted) rule 2 and 3 (selector, never truncate); PAT-ARCH-006 (the model; no new shared code).

### WP-3: `build_rules_prompt` pure prompt builder
- **Files:**
  - edit `app/intelligence/prompt_builders.py` (add constants and one function; do not change any existing function)
  - new `tests/test_rules_prompt.py`
- **Inputs:** none from other WPs. `prompt_builders.py` already has `from __future__ import annotations`, `from typing import Any`, `DM_ROLE_PROMPT` and `build_narrator_prompt`; do not use either in the new function.
- **Outputs:** in `app/intelligence/prompt_builders.py`:
  - `_RULES_EDITION_LABELS = {"5e": "SRD 5.1 (2014)", "5.5e": "SRD 5.2 (2024)"}`; any other value (including `None`) renders as `"edition unknown"`.
  - `RULES_DIRECTIVES_GROUNDED` = the lines `"DIRECTIVES:"`, `"- Answer as a D&D rules referee in plain language, using the rules excerpts above."`, `"- Name the rule you rely on and give the answer first."`, `"- If the excerpts do not answer the question, say so instead of guessing."`, `"- Do not narrate, role-play or describe the scene."` joined by `"\n"`.
  - `RULES_DIRECTIVES_TRAINING` = `"DIRECTIVES:"`, `"- Answer as a D&D 5e rules referee in plain language, from your general knowledge of the rules."`, `"- Give the answer first, then the rule name if you know it."`, `"- If you are not sure, say so instead of guessing."`, `"- Do not narrate, role-play or describe the scene."` joined by `"\n"`.
  - `build_rules_prompt(question: str, excerpts: Sequence[Mapping[str, str | None]]) -> str`.
  - Tests T-14 to T-17.
- **Acceptance criteria:**
  - Each excerpt is a plain mapping with keys `name`, `edition`, `text`. The function takes no settings object, no pydantic model, no store dict, does no I/O and does not log (PAT-ARCH-003: pure builder; one-shot string under the carve-out).
  - With at least one excerpt the prompt is the three parts joined with `"\n\n"`, in this order: (1) `"RULES EXCERPTS (SRD):"` followed by a blank line and then each excerpt rendered as `f"[{i}] {name} ({edition_label})\n{text}"` (`i` from 1, input order), excerpts separated by a blank line; (2) `f"QUESTION: {question.strip()}"`; (3) `RULES_DIRECTIVES_GROUNDED`. Excerpt text is inserted verbatim (no stripping, truncation or escaping).
  - With an empty excerpt sequence the prompt is `f"QUESTION: {question.strip()}"` joined by `"\n\n"` with `RULES_DIRECTIVES_TRAINING` (no `"RULES EXCERPTS"` heading).
  - The excerpts come before the question, and the question before the directives, in both modes, so an over-long prompt trimmed from the front loses excerpt text first.
  - The output never contains `DM_ROLE_PROMPT`, `"SYS:"`, `"VOICE:"`, `"TONE:"`, `"PERSONA:"` or `"Dungeon Master"`; the function body does not mention `NarratorVoiceParams`, `DM_ROLE_PROMPT` or `build_narrator_prompt`.
  - Inputs are not mutated; the result is deterministic. `build_narrator_prompt` and every other existing builder are unchanged.
  - T-14 to T-17 pass and the gate is green.
- **Patterns used/created:** PAT-ARCH-003 (accepted; one-shot pure builder carve-out), PAT-ARCH-009 (accepted) rule 4.

### WP-4: ingest support for the `rules` dataset (script only)
- **Files:**
  - edit `scripts/ingest_open5e.py`
  - new `tests/test_ingest_rules.py`
- **Inputs:** WP-2 (`Rule`, `app.reference.rules.Rule` used by T-22). The ingest script's existing functions (V9). `dnd_data/` is **not** needed: every test builds its input inline. Raw `rules` entries have `document` as a plain string and `desc` instead of `descriptions[]` (V10).
- **Outputs:**
  - `DOCUMENT_ALLOWLIST["rules"] = DEFAULT_DOCUMENTS` (that is `["srd-2014", "srd-2024"]`, SRD 5.1 and 5.2 only).
  - `PROJECTION["rules"] = ("id", "name", "edition", "source", "publisher", "third_party", "source_key", "description")` (same tuple as `conditions`).
  - `CONSUMERS["rules"] = "/rules tool (REQ-0024)"` (PAT-ARCH-007 rule 2: the named consumer is the tool, not a route).
  - New public function `resolve_documents(entries: list[dict], documents: dict[str, dict]) -> list[dict]`: returns a new list in which every entry whose `document` is a `str` is replaced by a shallow copy with `document` set to `documents[that key]`; entries whose `document` is already a dict are returned unchanged; an unknown document key raises `ValueError(f"unknown document {key!r} for entry {entry['key']!r}")`; inputs are not mutated.
  - In `_flatten`: when `dataset == "rules"`, `flat["description"] = raw["desc"]` (verbatim; raise `ValueError` if `raw["desc"]` is not a `str`) instead of calling `_description`, and `flat["id_fallbacks"] = [_slug(raw["key"])]`. Other datasets behave exactly as before.
  - In `_id_candidates`: after computing the existing list, append `record.get("id_fallbacks", [])` (empty for every dataset except `rules`), so the existing candidates keep their priority and nothing changes for `weapons` or `conditions`.
  - In `ingest`: for `dataset == "rules"`, load `_documents.json` **before** building records; if it is absent raise `ValueError` mentioning `_documents.json` (nothing written); set `entries = resolve_documents(entries, documents)`; the rest of the function (`build_records`, `check_budget`, attribution, OGL copy) is unchanged and sees resolved entries. Other datasets keep the current behaviour (including the `ingest.documents_missing` warning).
  - Tests T-18 to T-23.
- **Acceptance criteria:**
  - A raw `rules` entry with `"document": "srd-2024"` and a matching `_documents.json` record is ingested; `source` is that record's `display_name`, `publisher` is `publisher.name`, `edition` is `"5.5e"` for `srd-2024` and `"5e"` for `srd-2014`, `third_party` is `False`, `source_key` is the raw `key`, `description` is the raw `desc` byte for byte (newlines, markdown tables and non-ASCII characters preserved).
  - A record has exactly the projected keys; `desc`, `index`, `initialHeaderLevel`, `ruleset`, `crossreferences`, `document`, `key`, `slug`, `document_key` and `id_fallbacks` are not in the output.
  - Only `srd-2014` and `srd-2024` entries are kept; any other document is dropped by the allowlist.
  - **Duplicate-name check:** two entries in the **same** document with the same name slug do not raise. The shared id order stays `slug` (2024) / `slug`, `slug-5e` (2014); only when those are all claimed does the rules-only fallback id `_slug(source_key)` (for example `srd-2014-b-cover`) apply. All ids match `^[a-z0-9]+(-[a-z0-9]+)*$` and are unique. The same situation for `weapons` still raises `ValueError` matching `no free id` (the shared rule is not weakened).
  - Re-running `ingest` on the same snapshot gives byte-identical output (ids are reserved by `source_key` from the existing file).
  - `ingest("rules", ...)` still enforces the 2,000,000-byte / 2,000-entry budget through the existing `check_budget`, and still writes `ATTRIBUTION.md` for the used documents only.
  - No other dataset's existing tests change; `tests/test_ingest_open5e.py`, `tests/test_open5e_attribution.py` and `tests/test_sync_open5e.py` pass unmodified. Nothing under `app/` imports `scripts` (existing T-26 test).
  - T-18 to T-23 pass and the gate is green.
- **Patterns used/created:** PAT-ARCH-007 (accepted: allowlist, projection, `source_key`, consumer gate, budget, attribution), PAT-ARCH-006 (accepted: normalize at ingest; edition and publisher separate; third-party flag).

### WP-5: generate and commit `app/reference/rules.json`; budget and dataset CI tests
- **Files:**
  - new `app/reference/rules.json` (generated by `python -m scripts.ingest_open5e rules`; never hand-edited)
  - `app/reference/ATTRIBUTION.md` and `app/reference/LICENSE-OGL.txt` (regenerated or copied by the same command; expected unchanged because both SRD documents are already covered, V12)
  - edit `tests/test_reference_budget.py` (register `rules`; add T-24)
  - new `tests/test_rules_dataset.py` (T-26)
- **Inputs:** WP-2 (`Rule`), WP-4 (ingest support). A local, gitignored `dnd_data/rules.json` and `dnd_data/_documents.json` (V15). If either is missing, **stop and report**; do not hand-write the dataset and do not run the sync script without the human's say-so.
- **Outputs:**
  - `app/reference/rules.json`: a JSON array written with `indent=2`, `ensure_ascii=False`, one record per kept raw entry (expected 283 = 227 `srd-2014` + 56 `srd-2024`; every raw `rules` entry is expected to be SRD).
  - In `tests/test_reference_budget.py`: `OPEN5E_MODELS` gains `"rules": ("app.reference.rules", "Rule")` and a new test (T-24) asserts the file is in `REFERENCE_FILES`, `<= 2_000_000` bytes and `1..2_000` entries. The module docstring line that says "WP-4 adds weapons" may be left alone.
  - `tests/test_rules_dataset.py` (T-26).
  - A short measurement note in the PR/commit message (not a file): entry count, bytes, how many ids used the `_slug(source_key)` fallback form (ids that start with `srd-2014-` or `srd-2024-`), how many entries have a `description` longer than 3,000 chars and longer than 6,000 chars, and the longest description length. This answers the ADR-0009 follow-up and informs the `num_ctx` open question; it is a report, not a gate.
- **Acceptance criteria:**
  - Running `python -m scripts.ingest_open5e rules` from the repo root twice produces byte-identical `app/reference/rules.json` (second run changes nothing, `git diff` empty).
  - `app/reference/rules.json` is at most 2,000,000 bytes and has at most 2,000 entries (expected about 300-400 KB). If the file exceeds 1,000,000 bytes or the entry count differs from the raw count of `srd-2014` plus `srd-2024` entries, **stop and report** (the projection or allowlist is wrong).
  - Every record has exactly the keys `id, name, edition, source, publisher, third_party, source_key, description`; editions are `"5e"` and `"5.5e"` only and both occur; `third_party` is `false` everywhere; `id`s and `source_key`s are unique.
  - `description` is verbatim upstream `desc`. Spot-check: the record whose `source_key` is `srd-2024_the-six-abilities_ability-scores` has the description beginning `"Each ability has a score from 1 to 20"` and containing the line `"|10–11| This represents the human average.|"` (this entry is the first in the raw snapshot, V10).
  - `load_entries(RULES_PATH, Rule, "rules")` returns all entries with no warning (T-25).
  - `ATTRIBUTION.md` still has exactly the `srd-2014` and `srd-2024` sections (`git diff` empty or whitespace-only); `LICENSE-OGL.txt` unchanged.
  - No file under `app/` references `dnd_data` or the open5e host (existing `test_t26_*` still pass).
  - T-24, T-25, T-26 pass, the existing parametrized budget test passes for `rules.json`, and the gate is green.
- **Patterns used/created:** PAT-ARCH-006 (accepted: canonical file in git, CI fails hard), PAT-ARCH-007 (accepted: 2 MB / 2,000 budget CI test, attribution).

### WP-6: load the catalog at startup (fail-soft)
- **Files:**
  - edit `app/services/build_services.py`
  - new `tests/test_rules_wiring.py`
- **Inputs:** WP-2 (`Rule`, `RULES_PATH`), WP-5 (committed `app/reference/rules.json`). Current code (V6): `reference = {"species": load_species(), "weapons": load_entries(WEAPONS_PATH, Weapon, "weapons")}`.
- **Outputs:**
  - Imports `from app.reference.rules import RULES_PATH, Rule` and adds `"rules": load_entries(RULES_PATH, Rule, "rules")` to the `reference` dict, after `"weapons"`. Nothing else in the function changes (the `reference` object is still the same dict placed in `tool_service.default_context["reference"]` and in the returned services).
  - Update the docstring sentence "the reference catalog next so the worker can read species" only if needed to mention rules; keep it to one clause.
  - Tests T-27, T-28.
- **Acceptance criteria:**
  - `build_services(...)["reference"]["rules"]` is a `list[Rule]` with as many entries as the raw array in `app/reference/rules.json`; `services["tool"].default_context["reference"] is services["reference"]`.
  - The file is read once, while services are built, through `load_entries` (the shared fail-soft loader). It is not read at import time and not on each tool call.
  - If the file is missing or invalid, `build_services` does not raise, `reference["rules"] == []`, exactly one WARNING (`reference.unavailable`, extras `dataset="rules"` and a reason such as `missing`) is logged, and `species` and `weapons` are unaffected.
  - The top-level services keys remain `{"session", "tool", "inference", "reference"}`; `tests/test_reference_wiring.py`, `tests/test_character_wiring.py`, `tests/test_reference_weapons_route.py` and `tests/test_tool_calling.py::test_build_services_wires_tool_service_into_inference` pass unmodified.
  - No route is added and no existing route or schema changes.
  - T-27, T-28 pass and the gate is green.
- **Patterns used/created:** PAT-ARCH-006 (accepted: load once, fail-soft at runtime, tools read memory), PAT-CODE-001 (accepted: the loader already logs through `get_logger`).

### WP-7: the `rules` tool module
- **Files:**
  - edit `app/intelligence/tools/rules.py` (created in WP-2; add `NAME`, `TRAINING_DISCLAIMER`, usage text, logger and `run`; keep `select_rules` and its helpers unchanged)
  - new `tests/test_rules_tool.py`
- **Inputs:** WP-1 (`PromptSettings.rules_budget_chars`), WP-2 (`select_rules`, `Rule`), WP-3 (`build_rules_prompt`), WP-6 (the catalog arrives as `context["reference"]["rules"]`; tests pass it inline). Precedent: `app/intelligence/tools/narrate.py` (V2).
- **Outputs:** in `app/intelligence/tools/rules.py`:
  - Imports: `from app.config import get_settings`, `from app.intelligence.prompt_builders import build_rules_prompt`, `from app.intelligence.tools import ToolError`, `from app.services.logger import get_logger`; `logger = get_logger(__name__)`. It does not import `build_narrator_prompt`, `NarratorVoiceParams`, `scripts`, `httpx`, and it never opens a file.
  - `NAME = "rules"`; `_USAGE = "Usage: /rules <your rules question>"`; `TRAINING_DISCLAIMER = "Not checked against the SRD rules text."`.
  - `run(args: str, context: dict) -> dict[str, Any]`.
  - Tests T-29 to T-38.
- **Acceptance criteria:**
  - `question = (args or "").strip()`; if empty, raise `ToolError(_USAGE)` before anything else (no catalog read, no `generate`).
  - Catalog: `reference = context.get("reference")`; `catalog = reference.get("rules") if isinstance(reference, dict) else None`; `catalog = catalog or []`. A missing `reference`, a missing `rules` key, `None` or an empty list means training mode and is **not** an error.
  - Budget: `get_settings().prompts.rules_budget_chars` (read per call through `get_settings`, so tests can monkeypatch `rules_tool.get_settings`).
  - `chosen = select_rules(question, catalog, budget)`; `excerpts = [{"name": r.name, "edition": r.edition, "text": r.description} for r in chosen]`; `prompt = build_rules_prompt(question, excerpts)`; exactly one call `reply = context["inference"].generate(prompt)`. Exceptions from `generate` (for example `IntelligenceError`) propagate unchanged.
  - If `chosen` is non-empty: result is `{"text": reply, "meta": {"tool": NAME, "source": "rules", "rule_ids": [r.id for r in chosen]}}`; `reply` is returned unchanged.
  - If `chosen` is empty (catalog missing or empty, budget 0, nothing relevant, or the best match is larger than the budget): result is `{"text": reply.rstrip() + "\n\n" + TRAINING_DISCLAIMER, "meta": {"tool": NAME, "source": "training", "rule_ids": []}}`. The sentence is appended by the tool, not requested from the model. `rule_ids` is always present.
  - `meta` has exactly the keys `tool`, `source`, `rule_ids`; it never carries the prompt, the question or rule text.
  - Logging: exactly one `logger.info("rules.consulted", extra={"source": ..., "rule_count": len(chosen), "excerpt_chars": sum(len(r.description) for r in chosen)})` per successful call. No question, prompt, rule text or rule name is logged anywhere, at any level.
  - The tool never touches `context["store"]`, never writes messages, never mutates the catalog, never reads `dnd_data/` or any file, and never calls open5e. No `NarratorVoiceParams`, `DM_ROLE_PROMPT` or `build_narrator_prompt` is used.
  - `narrate.py`, `roll.py` and their tests are untouched and pass.
  - T-29 to T-38 pass and the gate is green.
- **Patterns used/created:** PAT-ARCH-004 (accepted: tool contract, `ToolError`, `meta`), PAT-ARCH-003 (accepted: pure builder, no prompt in logs), PAT-ARCH-009 (accepted: all seven rules), PAT-ARCH-006 (accepted: tools read memory), PAT-CODE-001 (accepted: `get_logger(__name__)`).

### WP-8: discovery and dispatch tests, tool contract doc, pattern examples
- **Files:**
  - edit `tests/test_tool_calling.py` (add T-39, T-40; do not change existing tests)
  - edit `tests/test_slash_dispatch.py` (add T-41, T-42; do not change existing tests)
  - edit `.github/instructions/tools.instructions.md`
  - edit `docs/patterns/architecture/PAT-ARCH-009-reference-grounded-llm-tools.md` (only its `## Examples` section; **do not change `status`**)
- **Inputs:** WP-1 to WP-7 complete. `FakeInference` (in `tests/test_tool_calling.py`) and `slash_env`, `_post`, `wait_idle` (in `tests/test_slash_dispatch.py`).
- **Outputs:**
  - T-39 to T-42 as in the Test Spec. T-41 and T-42 import `build_rules_prompt` from `app.intelligence.prompt_builders` and `TRAINING_DISCLAIMER` from `app.intelligence.tools.rules`, and `Rule` from `app.reference.rules`.
  - `.github/instructions/tools.instructions.md`: add one bullet under the Context bullet (keep every other line): "`context["reference"]` is the in-memory reference catalog (`{"species": [...], "weapons": [...], "rules": [...]}`), set by `build_services`; read it, never open `app/reference/*.json` or `dnd_data/`. A tool that puts catalog text into a prompt follows PAT-ARCH-009 (accepted): deterministic selection, a chars budget from settings, never truncate an entry, `meta.source` is the dataset name or `training` with an always-present id list, and a training reply gets a fixed 'not checked' sentence. `/rules` is the example." Also add `tests/test_rules_tool.py` to the final "Tests must not need network or Ollama" bullet's example list.
  - `PAT-ARCH-009` `## Examples`: replace the "None yet. Planned: ..." text with the real paths: `app/intelligence/tools/rules.py`, `build_rules_prompt` in `app/intelligence/prompt_builders.py`, `prompts.rules_budget_chars` in `app/config.py` and `settings.json`, `app/reference/rules.py`, `app/reference/rules.json`, and tests `tests/test_rules_selection.py`, `tests/test_rules_prompt.py`, `tests/test_rules_tool.py`, `tests/test_rules_wiring.py`.
- **Acceptance criteria:**
  - T-39: discovery lists `rules` as `app.intelligence.tools.rules`, the registry from `get_registry(refresh=True)` equals the `ToolService` list and includes `roll`, `narrate`, `rules`.
  - T-40: through `ToolService.invoke`, a client-supplied `reference` is dropped and the server catalog is used (`source == "rules"`, `rule_ids == [rule.id]`).
  - T-41: `/rules what is a bonus action` through the worker with the stubbed `client.chat` and no catalog gives an assistant reply `"stub reply\n\n" + TRAINING_DISCLAIMER` with `meta == {"tool": "rules", "source": "training", "rule_ids": [], "reply_to": <user id>}` and exactly one stubbed chat call whose content is `build_rules_prompt("what is a bonus action", [])`; the user message is `completed`.
  - T-42: with a catalog placed in `slash_env.ts.default_context["reference"]`, `/rules how do opportunity attacks work` gives `"stub reply"` with `meta == {"tool": "rules", "source": "rules", "rule_ids": ["opportunity-attacks"], "reply_to": <user id>}` and the one chat call's content contains the rule description.
  - The doc edits are additive; `PAT-ARCH-009` front matter (`status: proposed`) is unchanged, and no other pattern file and no ADR file is edited. No pattern is marked accepted.
  - All existing tests in both test files still pass and the gate is green.
  - Manual (not CI, report in the PR note): run the 10-question smoke list in section 4 against the live app with Ollama and record, per question, whether `meta.source` was `rules` or `training`.
- **Patterns used/created:** PAT-ARCH-004 (accepted), PAT-ARCH-009 (accepted; examples only).

## 4. Other Details

- **Risks:**
  1. **Context window (ADR-0009 F9, open question 3):** `OllamaClient.chat` sends no `num_ctx`, so the server default context applies. If it is 2,048 tokens, a 6,000-char budget (about 1,500 tokens) plus instructions and a reply can be trimmed. Mitigation: excerpts come first and the question and directives last (so trimming from the front loses excerpt text first); the budget is one number in `settings.json` (set about 3000 if needed, no code change). Raising `num_ctx` in the client is out of scope because it would change `/narrate` and chat.
  2. **Recall:** the selection is lexical, so paraphrased questions ("can they hit me when I run away?") miss and fall back to training mode. The fallback is flagged by `meta.source` and the fixed disclaimer, which also makes the rate measurable from stored messages. Stopwords, weights and `MIN_SCORE` are module constants and will need hobby-level tuning.
  3. **Edition mix:** both SRDs are in the catalog; the `5.5e`-first tie-break can show 2024 text to a table that plays 2014. The edition label is printed in the prompt excerpt header. Rule text that exists in both editions under different names is not de-duplicated.
  4. **Ids are permanent once committed.** Ingest reserves ids by `source_key` on re-ingest. Same-document duplicate names get `_slug(source_key)` ids that look unlike the others; they are ugly but stable.
  5. **Unmeasured at spec time:** the number of same-document duplicate names, the projected file size and the longest-entry distribution were not measured (no execution tool while writing the spec). The fallback id rule makes ingest safe whatever the count; WP-5 measures and reports.
  6. **`reference` is not in `SERVER_CONTEXT_KEYS`** (V7). In production `build_services` always places it in `default_context`, which makes it client-proof. A `ToolService` built without a `reference` default (tests) would accept a client-supplied one. `ToolService` is not changed by this spec.
  7. **Verbatim text and licensing:** `rules.json` carries verbatim SRD 5.1 / 5.2 text. `ATTRIBUTION.md` and `LICENSE-OGL.txt` already cover both documents (V12). The REQ-0018 "short summaries" sentence is read as species/consultant-scoped (ADR-0009 decision 9); that reading is pending sign-off (open question 4).
  8. **Worker time:** one `generate` call per `/rules`, the same as `/narrate`; no second call.
  9. **Prompt size of the question:** no length cap is added by this spec (same as `/narrate`); the transport limits apply.
  10. **Rule text in prompts is reviewed, static SRD text**, so prompt-injection risk is low; no sanitising is added.

- **Rollback plan:** all changes are additive. Revert the WP commits in reverse order. By hand: delete `app/intelligence/tools/rules.py`, `app/reference/rules.py`, `app/reference/rules.json` and the new test files (`tests/test_rules_*.py`, `tests/test_ingest_rules.py`); remove the `rules` entry from `reference` and the two imports in `app/services/build_services.py`; remove `build_rules_prompt`, its two directive constants and its edition-label map from `app/intelligence/prompt_builders.py`; remove `rules_budget_chars` from `PromptSettings` and `settings.json`; remove the `rules` entries from `DOCUMENT_ALLOWLIST`, `PROJECTION`, `CONSUMERS`, `resolve_documents`, and the `rules` branches in `_flatten`, `_id_candidates` and `ingest` in `scripts/ingest_open5e.py`; remove the `rules` entry and the T-24 test from `tests/test_reference_budget.py`; remove the added tests in `tests/test_tool_calling.py` and `tests/test_slash_dispatch.py`; undo the two doc edits. `/rules` then becomes an unknown tool (user message marked `error`). `dnd_data/` is untouched. No stored data refers to rule ids, so nothing needs migrating. The off-switch without any rollback is `prompts.rules_budget_chars = 0` (always training mode).

- **Patterns applied/created:**
  - PAT-ARCH-003 (accepted): one-shot pure builder, no prompt in logs.
  - PAT-ARCH-004 (accepted): tool contract, worker dispatch, `meta`.
  - PAT-ARCH-006 (accepted): normalized file in git, `load_entries`, fail-soft at runtime, CI fails hard, tools read the in-memory catalog. Its proposed wording changes (below) are **not** applied.
  - PAT-ARCH-007 (accepted): consumer-gated ingest, allowlist, projection, `source_key`, budget CI test, attribution.
  - PAT-CODE-001 (accepted): `get_logger`, no prompt text in logs.
  - PAT-ARCH-009 (**proposed**, created by the architect with ADR-0009): this spec is its first use. WP-8 only updates its Examples section; its status is not changed.
  - **New patterns created by this spec: none.** No reusable code or spec pattern beyond PAT-ARCH-009 was found while scoping. (The "same-document duplicate id" fallback is rules-only and has one call site, so it is not a pattern.)

- **Spec corrections found during implementation:** upstream SRD 5.1 `source_key`s start `srd_` (not `srd-2014_`); T-26 accepts `srd_` and `srd-2024_`. T-23 weapons guard needs three same-name `srd-2014` entries (two get `slug` and `slug-5e`). Example keys in T-21 are illustrative.
- **Resolved by the human on 2026-11-01:** ADR-0009 and PAT-ARCH-009 accepted; PAT-ARCH-006 wording changes and the REQ-0018 scoping note approved and applied; tool name `/rules` confirmed; 2024 (`srd-2024`, `5.5e`) preferred on ties; Ollama `num_ctx` is 4096 so the 6,000-char budget default stands. Items 1-4 below are closed.

- **Open questions (do not block; the ADR default is used and marked):**
  1. **Tool name `/rules` (confirm).** Default used: `rules`. Renaming later means renaming `rules.py`'s `NAME`, the `/rules` strings in tests, the usage message and the docs.
  2. **2014 vs 2024 tie-break.** Default used: `5.5e` (`srd-2024`) first on equal score, and `5.5e` wins when the same-named rule exists in both editions at equal score (`_EDITION_RANK` in `app/intelligence/tools/rules.py`). The human may prefer `5e` first, or a settings switch; that would be a follow-up requirement.
  3. **Ollama `num_ctx` / budget default.** Default used: 6,000 chars (ADR-0009). If the installed Ollama's default context is 2,048 tokens, set `prompts.rules_budget_chars` to about 3,000 in `settings.json`. The installed version has not been verified; WP-5's description-length report helps decide. Raising `num_ctx` in the client is not done here.
  4. **PAT-ARCH-006 wording change and REQ-0018 scoping note.** The ADR proposes (a) PAT-ARCH-006 rule 5: a dataset consumed only by backend tools MAY have no GET route, and (b) PAT-ARCH-006 rule 3: SRD allowlisted documents MAY carry verbatim text when `ATTRIBUTION.md` covers them; plus a note on REQ-0018 that its "short summaries" sentence is species/consultant-scoped. All are **pending human sign-off and not applied** by this spec. Until signed off, the rules dataset has no GET route (consistent with REQ-0024) and carries verbatim SRD text.
  5. **Not asked in the brief, listed for completeness:** a future `GET /api/v1/reference/rules` route (out of scope; about 10 lines plus a response model when wanted).

- **Ambiguities not resolvable from the ADR (spec chose a value; flag if wrong):**
  - The ADR says "a rule must clear a minimum score" and "up to about 3 rules" without numbers. The spec fixes `NAME_WEIGHT=3`, `TEXT_WEIGHT=1`, `MIN_SCORE=3`, `MAX_RULES=3`, the stopword list and the plural-folding rule (WP-2). These are tuning values.
  - "Keep only the preferred edition" when one rule appears in both editions: the spec keeps the first entry in rank order (score first, then edition), so `5.5e` wins on equal score but a `5e` entry with a strictly higher score wins. It could instead mean "always `5.5e`".
  - Exact disclaimer wording: the ADR gives only an example. The spec fixes `"Not checked against the SRD rules text."`.
  - The exact prompt wording (`RULES EXCERPTS (SRD):`, `QUESTION:`, `DIRECTIVES:` lines) is the spec's choice; the ADR fixes only the order (excerpts, question, directives).
  - The id fallback for same-document duplicate names (`_slug(source_key)`) is the spec's choice among the ADR's "for example a ruleset-prefixed slug"; `_slug(source_key)` is used because upstream keys are unique.
  - The `CONSUMERS["rules"]` value is a tool description string; the existing value for `weapons` is a route string and ingest only tests membership.
  - The `meta.reply_to` key in T-41/T-42 comes from the worker (PAT-ARCH-004), not from the tool.
  - Whether the ADR's measured numbers (283 entries, 297,000 chars) are correct was not re-verified; only the raw field shape was.

- **Manual smoke list (not CI; run once after WP-8 against live Ollama, record `meta.source` for each; hit or miss is information, not a failure):**
  1. `/rules how does an opportunity attack work`
  2. `/rules how does cover work`
  3. `/rules what is advantage and disadvantage`
  4. `/rules how does surprise work`
  5. `/rules how does a short rest work`
  6. `/rules what is a death saving throw`
  7. `/rules when can I use a bonus action`
  8. `/rules how does two-weapon fighting work`
  9. `/rules what does grappled do`
  10. `/rules can they hit me when I run away`

- **Non-goals:**
  - Any read-only `GET` route for `rules` (ADR-0009 decision 3; REQ-0024 freezes the reference routes), any new response model, any OpenAPI change.
  - Any change to `/narrate`, `/roll`, the `/attack` work (REQ-0022), the species or weapons datasets and routes, `OllamaClient` (including `num_ctx`), the inference worker, `ToolService` or `SERVER_CONTEXT_KEYS`.
  - LLM-assisted or embedding-based selection, a second `generate` call, a shared retrieval module (extract only when a second grounded tool exists).
  - Ingesting other open5e datasets (conditions, spells, creatures, sections, ...) or third-party documents into `rules.json`.
  - Truncating an excerpt to fit the budget; streaming; frontend work; UI for `meta.source`.
  - Editing `docs/requirements/LOG.md`, `.github/BACKLOG.json`, ADR-0009, `PAT-ARCH-006` or `REQ-0018`; marking anything `accepted`.
  - Calling open5e or reading `dnd_data/` from the app at runtime (the sync script is not run by this spec's tests).
