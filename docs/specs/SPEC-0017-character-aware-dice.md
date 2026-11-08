---
id: SPEC-0017
requirement: REQ-0022
adr: null
status: draft
date: 2026-11-07
---

# Character-aware dice: `/roll` ability terms and the `/attack` tool

## 1. Requirement
REQ-0022; restatement in [`docs/requirements/LOG.md`](../requirements/LOG.md) (row `REQ-0022`). ADR: none (see section 4). Depends on REQ-0020 (character stored on the session, done). Decisions the work packages rely on:
- The character is read-only data: tools call `context["store"].get_character(context["session_id"])` through one helper (no store import, nothing written); the stored dict is never mutated.
- `/roll` gains six ability words (`str dex con int wis cha`) as ordinary terms whose value is the modifier `(score-10)//2`; a bare ability word means `1d20+<word>`. Expressions without an ability word behave exactly as today and never touch the store.
- Ability heuristic (MVP): weapon has `Finesse` -> better of STR/DEX (tie: STR); else `Ammunition` (ranged) -> DEX; else STR. No proficiency bonus, no spell attacks (stated in help text).
- `/attack <weapon> [vs <AC>]`: roll `1d20+mod`; nat 20 always hits and doubles the damage dice (flat parts and the modifier are not doubled); nat 1 always misses; otherwise hit iff total >= AC; with no AC, hit is unknown (`null`) unless nat 20/1. Damage `dice+mod` (floored at 0) is rolled only when hit is true. No HP tracking.
- Weapon lookup is by name in `context["reference"]["weapons"]` (`Weapon` models): exact name first, else a unique substring; ties between same-named entries resolve 5.5e, then non-third-party, then id.

## 2. Test Spec
All tests are pytest, deterministic and need no network or Ollama. Use the `ScriptedRng` pattern from `tests/test_roll.py` (`randint(1, sides)` pops the next scripted value and records calls). The sample character is `ARIA` with `abilities` STR 12 (+1), DEX 16 (+3), CON 13, INT 11, WIS 15, CHA 10. Tool-level tests pass a hand-made context `{"rng": ..., "store": StubStore, "session_id": "s1", "reference": {"weapons": [Weapon(...)]}}` where `StubStore.get_character` returns a deepcopy of a dict and records calls (no other methods exist, so any write fails). `tests/test_roll.py`, `tests/test_slash_dispatch.py` and `tests/test_tool_calling.py` MUST keep passing.

### WP-1
File `tests/test_character_mods.py`.
- T-1.1 `ability_modifier`: 1 -> -5, 8 -> -1, 9 -> -1, 10 -> 0, 11 -> 0, 12 -> 1, 20 -> 5, 30 -> 10.
- T-1.2 `ability_modifiers(ARIA)` == `{"STR":1,"DEX":3,"CON":1,"INT":0,"WIS":2,"CHA":0}`; a character without `abilities` -> `{}`; non-int or bool scores are skipped.
- T-1.3 `weapon_ability(["Finesse","Light"], mods)`: STR 12/DEX 16 -> `("DEX", 3)`; STR 18/DEX 10 -> `("STR", 4)`; equal -> `("STR", n)`; property match is case-insensitive.
- T-1.4 `["Ammunition","Loading"]` -> DEX even when STR is higher; `["Finesse","Ammunition"]` follows the finesse rule; `["Thrown"]`, `["Versatile"]` and `[]` -> STR.
- T-1.5 `require_character`: returns the dict; `get_character` -> `None`, a `KeyError`, a missing `store` or a missing `session_id` each raise `ToolError` whose message starts with `No character`.
- T-1.6 purity: arguments equal a prior deepcopy after each call.

### WP-2
File `tests/test_roll_character.py`.
- T-2.1 `1d20+dex`, rng `[14]` -> text `1d20+dex: [14] + DEX(+3) = 17`; `meta.total` 17; `meta.terms[1] == {"sign":"+","ability":"DEX","modifier":3,"value":3}`.
- T-2.2 `adv+str`, rng `[7, 15]` -> total 16 (15 + STR +1). Upper-case `1D20+DEX` works.
- T-2.3 STR 8 (-1): `1d20+str`, rng `[10]` -> total 9, text contains `+ STR(-1)`; `1d20-str` -> total 11 (sign inverts the modifier).
- T-2.4 bare `dex`, rng `[10]` -> `meta.expression == "1d20+dex"`, total 13; bare `5` is still a constant (`rng.calls == []`).
- T-2.5 character missing (store returns `None`, or no `store` in context) with `1d20+dex` -> `ToolError("No character ...")` and `rng.calls == []`.
- T-2.6 `2d6+3` with a store that raises on any access still succeeds (the store is read only when an ability term is present).
- T-2.7 `1d20+foo`, `1d20+strx` -> `ToolError` with the unchanged `INVALID` text from `tests/test_roll.py`, raised before any store read or rng call; ability terms count toward `MAX_TERMS`.
- T-2.8 the stub store only ever saw `get_character("s1")`; the character dict it returned is unchanged.
- T-2.9 `run("help", ctx)` returns text containing `dex` and `adv` and calls neither the rng nor the store; blank args still roll `1d20`.

### WP-3
File `tests/test_attack_tool.py`. Weapons are built with `Weapon(...)` (all required fields) and real `properties` spellings (`"Finesse"`, `"Ammunition"`).
- T-3.1 Longsword (`1d8`, `["Versatile"]`) `vs 12`, rng `[14, 5]` -> attack `1d20+1` total 15, hit; damage `1d8+1` = 6. `meta` has `tool:"attack"`, `weapon`, `weapon_id`, `ability:"STR"`, `modifier:1`, `ac:12`, `attack_roll:14`, `attack_total:15`, `hit:true`, `critical:false`, `damage:6`; rng calls `[(1,20),(1,8)]`.
- T-3.2 miss: rng `[3]` `vs 15` -> `hit:false`, `damage:null`, one rng call, text contains `Miss`. Total equal to AC hits.
- T-3.3 no `vs`: rng `[10]` -> `ac:null`, `hit:null`, `damage:null`, one rng call, text contains the attack total and says no AC was given.
- T-3.4 nat 20 `vs 30`, rng `[20, 3, 4]` -> hit, `critical:true`, damage expression `2d8+1`, damage 8, text contains `Critical hit`. Nat 20 with no AC also hits and rolls damage. Weapon with flat `damage_dice` `"1"` on a crit stays `1+mod` (no doubling).
- T-3.5 nat 1 `vs 2` with total >= 2 -> still `hit:false`, no damage; nat 1 with no AC -> `hit:false`.
- T-3.6 heuristic: Dagger (`Finesse`) with DEX 16/STR 12 -> `DEX`, modifier 3; with STR 18/DEX 10 -> `STR`; Shortbow (`Ammunition`) -> `DEX`; Warhammer -> `STR`.
- T-3.7 STR 1 (-5), Club `1d4`, `vs 10`, rng `[15, 1]` -> hit (15-5=10 >= 10), `damage == 0` (floored), no negative. (Without `vs` an attack never hits, so no damage is rolled.)
- T-3.8 parsing: `"  LongSword  VS  15 "` works; `vs abc`, `vs 0`, `vs 41`, a missing weapon before `vs`, and blank args raise `ToolError` (blank/usage errors contain the `HELP` text); rng untouched.
- T-3.9 lookup: unknown name -> `ToolError("Unknown weapon ...")`; `sword` over Longsword/Greatsword/Shortsword -> `ToolError` naming up to 5 candidates sorted by name; exact `Club` beats substring `Greatclub`; unique substring `halber` -> Halberd; two entries named `Dagger` (5e, 5.5e) resolve to 5.5e whatever the catalog order.
- T-3.10 errors: no character -> `ToolError("No character ...")`; missing/empty `reference["weapons"]` -> `ToolError` mentioning the catalog; `damage_dice` `None` or unparsable -> `ToolError`; rng untouched in each.
- T-3.11 no mutation: character dict and `Weapon` unchanged; `StubStore` saw only `get_character`.
- T-3.12 `run("help", ctx)` text contains `proficiency` and `spell` and `out of scope` (lower-case, case-sensitive); the module exposes `NAME == "attack"`.
- T-3.13 real catalog sweep: load `app/reference/weapons.json` through `load_entries(WEAPONS_PATH, Weapon, "weapons")`; for every weapon with `damage_dice` not `None`, the damage expression builder (normal and crit) yields an expression `roll.evaluate` accepts (covers `"1"` and `"0"`).

### WP-4
File `tests/test_character_dice_dispatch.py` (fixture modelled on `prod_env` in `tests/test_slash_dispatch.py`: `build_services(repos, enable_tool_discovery=True)`, session `s1` created with `character=ARIA`, `client.chat` stubbed, `services["tool"].default_context["rng"] = ScriptedRng(...)`), plus an added test in `tests/test_tool_calling.py`.
- T-4.1 `ToolService(discover_on_init=True).list_tools()["attack"] == "app.intelligence.tools.attack"`, and `get_registry(refresh=True)` names equal the service names and include `attack`.
- T-4.2 WebSocket or REST `/attack Dagger vs 12` (real catalog) -> assistant reply with `meta.tool == "attack"`, `meta.reply_to` the user message id, user message `completed`, `chat_calls == []`; stored character equals `ARIA` afterwards.
- T-4.3 `/roll 1d20+dex` end to end -> reply content `1d20+dex: [N] + DEX(+3) = ...`, `meta.tool == "roll"`.
- T-4.4 a session created without a character: `/attack Dagger` and `/roll dex` mark the user message `error` with a `No character` message; the worker keeps running (a following `/roll 1d6` succeeds).
- T-4.5 `/attack nonsense` marks the user message `error` ("Unknown weapon"); `/attack help` completes with a reply whose content contains `proficiency`.

### WP-5
No JS test runner exists and none is added.
- T-5.1 `cd frontend && npm run build` exits 0 (type-check plus Vite build).
- T-5.2 manual smoke (recorded in the PR, not automated): with a character the weapon picker lists weapons, Attack sends `/attack <name>` or `/attack <name> vs <AC>`; without a character the Attack button is disabled; with the weapons request failing the tray shows no picker and the dice work as before.

## 3. Work Packages

### WP-1: Character modifier helper
- **Files:** `app/intelligence/character_mods.py` (new, not under `tools/` so discovery ignores it); `tests/test_character_mods.py` (new).
- **Inputs:** a character dict as stored (`abilities` keys `STR DEX CON INT WIS CHA`, int scores 1-30); weapon `properties` as a list of strings such as `"Finesse"`, `"Ammunition"`; `app.intelligence.tools.ToolError`; the tool context dict.
- **Outputs:** `ABILITIES` tuple in the order above; `ability_modifier(score: int) -> int` = `(score - 10) // 2`; `ability_modifiers(character: dict) -> dict[str, int]` (only keys present with a real int, bool excluded; `{}` when `abilities` is absent); `weapon_ability(properties, mods) -> tuple[str, int]` returning `(ability_key, modifier)` using the finesse/ammunition/STR rule (case-insensitive property match, finesse checked first, tie -> STR, missing key counts as 0); `NO_CHARACTER = "No character on this session. Create or select a character first."`; `require_character(context) -> dict` which reads `context.get("store")` and `context.get("session_id")`, calls `store.get_character(session_id)` and raises `ToolError(NO_CHARACTER)` when either is missing, the call raises `KeyError`, or the result is `None`. It never writes and imports no store or repos module. The first three functions are pure.
- **Acceptance criteria:** every test in Test Spec WP-1 passes; no argument is mutated; the module imports only stdlib and `ToolError`; `tests/test_patterns.py` still passes.
- **Patterns used/created:** PAT-ARCH-004 (tool reads context, raises `ToolError`), PAT-CODE-001 (no print/getLogger).

### WP-2: `/roll` character modifiers
- **Files:** `app/intelligence/tools/roll.py` (edit); `tests/test_roll_character.py` (new). `tests/test_roll.py` is not edited and must still pass.
- **Inputs:** WP-1's `app/intelligence/character_mods.py` (`ability_modifiers`, `require_character`, `ABILITIES`); the existing grammar in `roll.py`.
- **Outputs:** (a) grammar extended: `term := dice | INT | 'adv' | 'dis' | ABILITY`, `ABILITY := str|dex|con|int|wis|cha` (case-insensitive, same whitespace rules, counts toward `MAX_TERMS`); (b) bare-ability shorthand: after trimming and lower-casing, text equal to one ability word becomes `1d20+<word>` before parsing (so `meta.expression` is `1d20+dex`); (c) `evaluate(expr, rng, mods=None)` keeps its two-argument form working; `run` calls `require_character(context)` and `ability_modifiers(...)` only when the parsed specs contain an ability term, after syntax and bound checks and before any roll; (d) an ability term renders `DEX(+3)` / `STR(-1)` in the text, contributes its modifier with the usual sign (`-str` subtracts the modifier) and its meta term is `{"sign", "ability", "modifier", "value"}`; (e) `HELP` string constant (usage, `adv`/`dis`, ability words with one example such as `/roll 1d20+dex`, and that ability terms need a session character) returned by `run("help", ...)` as `{"text": HELP, "meta": {"tool": "roll", "help": True}}` without rng or store use. The existing `_USAGE` text MUST NOT change (tests assert it).
- **Acceptance criteria:** every test in Test Spec WP-2 passes; existing `tests/test_roll.py` passes unchanged; an expression without ability words behaves byte-for-byte as before and never reads `context["store"]`; an invalid expression still raises `ToolError` before any rng call or store read; a missing character raises `ToolError` (message starts `No character`) before any rng call.
- **Patterns used/created:** PAT-ARCH-004.

### WP-3: Weapon lookup and `/attack` tool
- **Files:** `app/intelligence/tools/attack.py` (new); `tests/test_attack_tool.py` (new).
- **Inputs:** `character_mods` (WP-1: `ability_modifiers`, `weapon_ability`, `require_character`); `app.intelligence.tools.roll.evaluate(expr, rng)` returning `{"text", "meta": {"total", "terms": [{"rolls": [...], ...}, ...]}}`; `context["reference"]["weapons"]`, a list of `Weapon` models (`id`, `name`, `edition` in `5e|5.5e|None`, `third_party`, `damage_dice` such as `"1d8"`, `"1"`, `"0"` or `None`, `properties` list); `context.get("rng")` (fall back to a module-level `random.Random()`).
- **Outputs:** module with `NAME = "attack"`, `run(args, context)` and a `HELP` constant. Behaviour: `help` returns HELP as the reply; blank args raise `ToolError(HELP)`. HELP states usage `/attack <weapon> [vs <AC>]`, the ability rule, the nat 1/nat 20 rule, that damage rolls only on a hit, and that proficiency bonus and spell attacks are out of scope. Parse: trim; if the lower-cased text contains ` vs ` split once on the last occurrence, the right side MUST be an integer 1-40 (else `ToolError` with HELP), the left side is the weapon name (non-empty). Lookup normalises names (casefold, non-alphanumerics to single spaces): exact normalised-name matches first; else entries whose name contains the query; if the remaining candidates share one normalised name, pick by `5.5e` before others, then `third_party` False first, then `id`; if they have several distinct names raise `ToolError` listing up to 5 names sorted; none -> `ToolError("Unknown weapon ...")`; empty or absent catalog -> `ToolError` mentioning the weapon catalog. `damage_dice` MUST match `^(\d{1,2})?d\d{1,3}$` or `^\d{1,3}$` else `ToolError`. Then `require_character`, `weapon_ability` for `(ability, mod)`. Attack expression `1d20` plus `mod` (omit when 0, sign as `+n`/`-n`) goes through `roll.evaluate`; nat = `meta["terms"][0]["rolls"][0]`. `hit` = True if nat 20, False if nat 1, else `total >= ac` when AC given, else `None`. Only when `hit is True` roll damage: the dice part of `damage_dice` (count doubled on nat 20; flat values unchanged) plus `mod`; `damage = max(0, total)`. Reply text: `<Weapon name> (<ABIL> <+/-mod>)[ vs AC n]: <attack text>. <Critical hit!|Hit!|Miss.|Natural 1: miss.|No AC given: roll the damage after the DM calls a hit.>` followed by ` Damage: <damage text>.` when rolled. Meta as listed in T-3.1 (including `critical`, `hit`, `damage`, `ac`).
- **Acceptance criteria:** every test in Test Spec WP-3 passes; the module imports no store or reference path and never writes anything; an error raised during parsing or lookup happens before any rng call; the same inputs and rng script always give the same result.
- **Patterns used/created:** PAT-ARCH-004; PAT-ARCH-006 (tool reads the in-memory catalog); PAT-ARCH-009 is not applicable (no LLM call, no prompt text).

### WP-4: Discovery, dispatch and tool contract doc
- **Files:** `tests/test_character_dice_dispatch.py` (new); `tests/test_tool_calling.py` (add one test, edit nothing else); `.github/instructions/tools.instructions.md` (add exactly one line, see below; the Implementer or the owner makes the edit, the spec writer did not).
- **Inputs:** WP-1 to WP-3 merged; `build_services`, `ToolService`, `get_registry`; fixtures and helpers in `tests/test_slash_dispatch.py` (`ScriptedRng`, `_ws_send_and_collect`, `prod_env` shape) and `tests/session_helpers.py`.
- **Outputs:** the tests in Test Spec WP-4; no production code change unless a test exposes a defect in WP-1 to WP-3 (then fix it in that module and say so). The one added doc line, placed after the `Context:` line: "A tool may read the session character with `character_mods.require_character(context)` (read-only `context["store"].get_character(context["session_id"])`, `ToolError` when absent); no other store access, and tools still never write." No worker change is needed: it already passes `store` and `session_id`.
- **Acceptance criteria:** every test in Test Spec WP-4 passes; `pytest tests/test_roll.py tests/test_slash_dispatch.py tests/test_tool_calling.py tests/test_patterns.py` is green; the doc line is the only change to `tools.instructions.md`.
- **Patterns used/created:** PAT-ARCH-004.

### WP-5: Frontend weapon picker in the dice tray
- **Files:** `frontend/src/types.ts` (add `Weapon`, `WeaponListResp`); `frontend/src/lib/api.ts` (add `getWeapons`); `frontend/src/components/DiceTray.tsx`; `frontend/src/App.tsx`.
- **Inputs:** backend `GET /api/v1/reference/weapons` returns `{"weapons": [...]}` (each with `id`, `name`, `edition`, `third_party`, `damage_dice`, `damage_type`, `properties`); the existing `getSpecies` in `api.ts` as the fetch pattern; `rollDice`/`sendText` and `sendableHero(roster, activeCharacterId)` in `App.tsx`.
- **Outputs:** `Weapon` type (those fields) and `WeaponListResp`; `getWeapons(): Promise<Weapon[]>`; `App` loads weapons once on mount, on failure keeps `[]` (no error banner), derives `hasCharacter = sendableHero(roster, activeCharacterId) !== null`, defines `attack(name, ac)` that sends `/attack ${name}` or `/attack ${name} vs ${ac}` through `sendText`, and passes `weapons`, `hasCharacter` and `onAttack` to `DiceTray`; `DiceTray` gets those three props (optional, defaults `[]`, `false`, no-op) and, only when `weapons.length > 0`, renders an Attack section below the custom roll: a `<select>` of weapon names (deduplicated by name, sorted), a number input for AC (1-40, optional, empty means no `vs`), and an Attack button; the button is disabled when `disabled`, no weapon is chosen or `!hasCharacter` (title explains "Needs a character"). Existing dice, adv/dis and custom-roll behaviour is unchanged.
- **Acceptance criteria:** T-5.1 passes (`npm run build` in `frontend/` exits 0, no new dependency in `package.json`); the manual smoke in T-5.2 holds; no JS test tooling is added; no backend file changes.
- **Patterns used/created:** none.

## 4. Other Details (at most ten lines)
- **ADR check:** none of the triggers fires: no new dependency, no schema or migration change, no deviation from an accepted pattern, one obvious approach, easily reversible. The one-line tool-doc addition clarifies how a tool reads the character (injected `store` via `require_character`) rather than changing the DI convention; having the worker add a `character` context key was the alternative and would touch server-owned keys, so it was rejected.
- **Risks:** `/attack` replies are not roll cards (frontend `rollMeta` keys on `meta.tool === 'roll'`) and the diary lists them as plain text; the Ammunition-as-ranged heuristic ignores thrown weapons without Finesse (STR, per SRD) and proficiency (documented, MVP).
- **Rollback plan:** revert the commit; no data, schema or settings change. The `/roll` ability terms are additive.
- **Patterns applied/created:** PAT-ARCH-004, PAT-ARCH-006, PAT-CODE-001 (all accepted); none created.
- **Non-goals:** proficiency bonus, spell attacks, HP/damage tracking, advantage/disadvantage on `/attack`, saving throws, roll-card rendering of attacks, ability buttons in the dice tray, any ADR or schema change.
