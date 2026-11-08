"""Deterministic world-mention detection for post-reply mining (SPEC-0019, REQ-0028).

Pure and stdlib-only (PAT-ARCH-012 rule 4): no store, HTTP, model client or logging. The
worker passes known entities (all statuses) and the caller stop list; the detector returns
which known entities the text names and which capitalised phrases are proposed as new
world entities. Rules are in SPEC-0019 WP-3.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

_PRONOUNS = tuple(
    "I me my mine we us our ours you your yours he him his she her hers it its they them "
    "their theirs this that these those who whom whose what which someone something anyone "
    "everyone nothing everything".split()
)
_OPENERS = tuple(
    "A An The And But Or Nor So Yet Then As When While Where If Because There Here Behind "
    "Before After Beneath Above Below Under Over Inside Outside Near Across From With Without "
    "In On At By For To Of Into Through Along Around Suddenly Meanwhile Still Now Make See "
    "Take Look No Yes Not Also Only Just All Each Every Some Both Oh".split()
)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_GODS = ("God", "Gods")
_ABILITIES = ("Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma")
_SKILLS = (
    "Acrobatics Arcana Athletics Deception History Insight Intimidation Investigation "
    "Medicine Nature Perception Performance Persuasion Religion Stealth Survival".split()
)
_CONDITIONS = (
    "Blinded Charmed Deafened Exhausted Frightened Grappled Incapacitated Invisible "
    "Paralyzed Petrified Poisoned Prone Restrained Stunned Unconscious".split()
)

BUILTIN_STOP_WORDS: tuple[str, ...] = (
    *_PRONOUNS,
    *_OPENERS,
    *_WEEKDAYS,
    *_GODS,
    *_ABILITIES,
    *_SKILLS,
    *_CONDITIONS,
)
BUILTIN_STOP_PHRASES: tuple[str, ...] = (
    "Player's Handbook",
    "Dungeon Master",
    "Monster Manual",
    "Animal Handling",
    "Sleight of Hand",
)
TITLE_WORDS: tuple[str, ...] = (
    "Lord",
    "Lady",
    "Sir",
    "Captain",
    "King",
    "Queen",
    "Master",
    "Mistress",
    "Elder",
    "Brother",
    "Sister",
)

_TITLES = frozenset(t.casefold() for t in TITLE_WORDS)
_TOKEN = re.compile(r"[a-z0-9]+")
_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*(?:(?<=s)['’](?=\s[A-Z]))?")
_POSSESSIVE = re.compile(r"['’][sS]\Z")
_SENTENCE_BREAK = re.compile(r'[.!?]["\'“”‘’]*(?=\s|\Z)|\n')
_SENTENCE_MARKS = " \t\"'“”‘’*_`#>"
_MAX_RUN_WORDS = 4
_MIN_SINGLE_CHARS = 3
_MAX_SNIPPET = 160

_CAP = "cap"
_CONN = "conn"
_OTHER = "other"


@dataclass(frozen=True)
class Candidate:
    name: str
    kind: str
    snippet: str
    count: int


@dataclass(frozen=True)
class Detection:
    matched_ids: tuple[str, ...]
    candidates: tuple[Candidate, ...]


@dataclass
class _Tally:
    name: str
    first: int
    count: int = 0
    single: bool = True
    plain: bool = False  # a single-word occurrence that is not sentence-initial


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(text.casefold()))


def _head(word: str) -> str:
    tokens = _tokens(word)
    return tokens[0] if tokens else ""


def _contains(seq: tuple[str, ...], sub: tuple[str, ...]) -> bool:
    n = len(sub)
    return any(seq[i : i + n] == sub for i in range(len(seq) - n + 1))


def _first_index(stream: tuple[str, ...], needle: tuple[str, ...]) -> int:
    n = len(needle)
    for i in range(len(stream) - n + 1):
        if stream[i : i + n] == needle:
            return i
    return -1


def _word_kind(word: str) -> str:
    if word in ("of", "the"):
        return _CONN
    if word[0].isupper() and any(c.islower() for c in word):
        return _CAP
    return _OTHER


def _adjacent(text: str, left: tuple, right: tuple) -> bool:
    return text[left[2] : right[1]] == " "


def _runs(text: str) -> list[list[tuple]]:
    """Maximal runs of capitalised words joined by single spaces (lowercase of/the allowed)."""
    items = [(m.group(), m.start(), m.end(), _word_kind(m.group())) for m in _WORD.finditer(text)]
    runs: list[list[tuple]] = []
    i = 0
    while i < len(items):
        if items[i][3] != _CAP:
            i += 1
            continue
        members = [items[i]]
        j = i + 1
        while True:
            k = j
            while (
                k < len(items) and items[k][3] == _CONN and _adjacent(text, items[k - 1], items[k])
            ):
                k += 1
            if k < len(items) and items[k][3] == _CAP and _adjacent(text, items[k - 1], items[k]):
                members.extend(items[j : k + 1])
                j = k + 1
            else:
                break
        runs.append(members)
        i = j
    return runs


def _sentence_start(text: str, pos: int) -> bool:
    i = pos
    while i > 0 and text[i - 1] in _SENTENCE_MARKS:
        i -= 1
    if i == 0 or text[i - 1] in ".!?\n":
        return True
    # An opening quote right after a comma or colon starts a spoken sentence; a bare
    # comma or colon (`The inn, Marta said`) does not.
    return text[i - 1] in ",:" and any(c in "\"“‘'" for c in text[i:pos])


def _snippet(text: str, pos: int) -> str:
    start, end = 0, len(text)
    for brk in _SENTENCE_BREAK.finditer(text):
        if brk.end() <= pos:
            start = brk.end()
        else:
            end = brk.end()
            break
    flat = " ".join(text[start:end].split())
    if len(flat) > _MAX_SNIPPET:
        flat = flat[: _MAX_SNIPPET - 1].rstrip() + "…"
    return flat


def _known_labels(item: Mapping) -> list[tuple[str, ...]]:
    labels = [item["name"], *(item.get("aliases") or ())]
    return [tokens for tokens in (_tokens(label) for label in labels) if tokens]


def detect_mentions(
    text: str,
    known: Sequence[Mapping],
    stoplist: Iterable[str] = (),
    max_candidates: int = 3,
) -> Detection:
    """Known entities named in `text` and up to `max_candidates` new capitalised phrases."""
    stop_phrases = {
        tokens
        for tokens in (_tokens(s) for s in (*BUILTIN_STOP_WORDS, *BUILTIN_STOP_PHRASES, *stoplist))
        if tokens
    }
    stop_heads = {phrase[0] for phrase in stop_phrases if len(phrase) == 1}
    known_labels = [(item["id"], _known_labels(item)) for item in known]

    stream = _tokens(text)
    hits: list[tuple[int, str]] = []
    for entity_id, labels in known_labels:
        firsts = [i for i in (_first_index(stream, lab) for lab in labels) if i >= 0]
        if firsts:
            hits.append((min(firsts), entity_id))
    hits.sort(key=lambda hit: hit[0])
    matched = tuple(dict.fromkeys(entity_id for _, entity_id in hits))

    excluded = set(stop_phrases)
    for _, labels in known_labels:
        excluded.update(labels)

    tallies: dict[tuple[str, ...], _Tally] = {}
    for members in _runs(text):
        if len(members) > _MAX_RUN_WORDS:
            continue
        start = members[0][1]
        words = [member[0] for member in members]
        words[-1] = _POSSESSIVE.sub("", words[-1])
        while words and (_word_kind(words[0]) != _CAP or _head(words[0]) in stop_heads):
            words.pop(0)
        if not words:
            continue
        name = " ".join(words)
        tokens = _tokens(name)
        if not tokens or any(_contains(phrase, tokens) for phrase in excluded):
            continue
        single = len(words) == 1
        tally = tallies.get(tokens)
        if tally is None:
            tally = tallies[tokens] = _Tally(name=name, first=start)
        tally.count += 1
        tally.single = tally.single and single
        if single and not _sentence_start(text, start):
            tally.plain = True

    multi = [tokens for tokens, tally in tallies.items() if not tally.single]
    accepted: list[tuple[str, ...]] = []
    for tokens, tally in tallies.items():
        if tally.single and (
            len(tally.name) < _MIN_SINGLE_CHARS
            or not tally.plain
            or any(_contains(other, tokens) for other in multi)
        ):
            continue
        accepted.append(tokens)
    accepted.sort(key=lambda t: (-tallies[t].count, tallies[t].first))

    candidates: list[Candidate] = []
    for tokens in accepted[: max(max_candidates, 0)]:
        tally = tallies[tokens]
        candidates.append(
            Candidate(
                name=tally.name,
                kind="npc" if tokens[0] in _TITLES else "other",
                snippet=_snippet(text, tally.first),
                count=tally.count,
            )
        )
    return Detection(matched_ids=matched, candidates=tuple(candidates))
