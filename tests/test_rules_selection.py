"""Rules selection (SPEC-0014, WP-2): `select_rules` over in-memory `Rule` objects.

T-04..T-13: name-weighted scoring, relevance threshold, tokenizing, edition tie-break,
same-name dedupe, the 3-entry cap, budget packing (never truncate), training-mode inputs and
purity. No network, no Ollama, no files: every catalog is built inline.
"""

import builtins

from app.intelligence.tools.rules import select_rules
from app.reference.rules import Rule


def _rule(id, name, description, edition="5.5e"):
    return Rule(
        id=id,
        name=name,
        edition=edition,
        source="SRD",
        publisher="Wizards of the Coast",
        third_party=False,
        source_key=f"srd_{id}",
        description=description,
    )


# T-04
def test_name_match_outranks_description_match():
    a = _rule("opportunity-attack", "Opportunity Attack", "A creature leaves your reach.")
    b = _rule(
        "reactions",
        "Reactions",
        "An opportunity attack is a reaction. Opportunity attack rules: attack when a creature "
        "leaves.",
    )
    # A: 2 name hits x3 + 1 text hit = 7. B: 0 name hits + 3 text hits = 3 (relevant).
    result = select_rules("opportunity attack leaves", [b, a], 6000)
    assert [r.id for r in result] == ["opportunity-attack", "reactions"]


# T-05
def test_description_only_relevance_needs_three_distinct_matches():
    x = _rule("notes", "Notes", "A creature that leaves your reach can be hit.")
    # 2 distinct description matches: below MIN_SCORE 3.
    assert select_rules("creature reach", [x], 6000) == []
    # 3 distinct description matches: relevant.
    assert select_rules("creature leaves reach", [x], 6000) == [x]


# T-06
def test_tokenizing_stopwords_punctuation_case_and_plurals():
    e = _rule("opportunity-attack", "Opportunity Attack", "A creature leaves your reach.")
    # Every token is a stopword.
    assert select_rules("What are the rules?", [e], 6000) == []
    assert select_rules("Can I use Opportunity Attacks?", [e], 6000) == [e]
    assert select_rules("opportunity-attack!!", [e], 6000) == [e]
    assert select_rules("OPPORTUNITY ATTACKS", [e], 6000) == [e]


# T-07
def test_edition_tie_break_then_id():
    # Equal score for "grappling"; names differ. The 5.5e entry wins even though its id
    # sorts later.
    old = _rule("a-hook", "Grappling Hook", "Short text.", edition="5e")
    new = _rule("z-check", "Grappling Check", "Short text.", edition="5.5e")
    assert [r.id for r in select_rules("grappling", [old, new], 6000)] == ["z-check", "a-hook"]

    # Equal score and equal edition: ordered by id ascending, regardless of input order.
    beta = _rule("beta-grapple", "Grappling Beta", "Short text.")
    alpha = _rule("alpha-grapple", "Grappling Alpha", "Short text.")
    assert [r.id for r in select_rules("grappling", [beta, alpha], 6000)] == [
        "alpha-grapple",
        "beta-grapple",
    ]


# T-08
def test_same_rule_in_both_editions_keeps_one():
    old = _rule("cover-5e", "Cover", "Half cover grants +2 AC.", edition="5e")
    new = _rule("cover", "Cover", "Half cover grants +2 AC.", edition="5.5e")
    assert select_rules("cover", [old, new], 6000) == [new]

    # Names differing only in case and punctuation are the same rule.
    punct = _rule("cover", "cover.", "Half cover grants +2 AC.", edition="5.5e")
    assert select_rules("cover", [old, punct], 6000) == [punct]


# T-09
def test_at_most_three_entries_top_by_score_edition_id():
    entries = [
        _rule("grapple-b", "Grapple B", "Short text.", edition="5e"),
        _rule("leap-grapple", "Grapple Leap", "Short text."),  # 2 name hits: score 6
        _rule("grapple-a", "Grapple A", "Short text."),
        _rule("grapple-d", "Grapple D", "Short text.", edition="5e"),
        _rule("grapple-c", "Grapple C", "Short text."),
    ]
    result = select_rules("grapple leap", entries, 100000)
    assert len(result) == 3
    assert [r.id for r in result] == ["leap-grapple", "grapple-a", "grapple-c"]


# T-10
def test_never_truncates_and_skips_what_does_not_fit():
    r1 = _rule("r1", "Grapple One", "x" * 400)
    r2 = _rule("r2", "Grapple Two", "x" * 500)
    r3 = _rule("r3", "Grapple Three", "x" * 100)
    result = select_rules("grapple", [r1, r2, r3], 600)
    assert result == [r1, r3]
    assert result[0].description == "x" * 400
    assert result[1].description == "x" * 100
    assert result[0] is r1
    assert result[1] is r3


# T-11
def test_best_match_too_big_means_training():
    r1 = _rule("r1", "Grapple One", "x" * 700)
    r2 = _rule("r2", "Grapple Two", "x" * 200)
    assert select_rules("grapple", [r1, r2], 600) == []


# T-12
def test_training_mode_inputs():
    perfect = _rule("cover", "Cover", "Half cover grants +2 AC.")
    assert select_rules("cover", [], 6000) == []
    assert select_rules("cover", [perfect], 0) == []
    assert select_rules("what are the rules?", [perfect], 6000) == []
    assert select_rules("cover", [perfect], -5) == []


# T-13
def test_selection_is_pure():
    a = _rule("opportunity-attack", "Opportunity Attack", "A creature leaves your reach.")
    b = _rule("reactions", "Reactions", "An opportunity attack is a reaction.")
    rules = [b, a]
    before_order = list(rules)
    before_dump = [r.model_dump() for r in rules]

    first = select_rules("opportunity attack", rules, 6000)
    second = select_rules("opportunity attack", rules, 6000)

    assert first == second
    assert rules == before_order
    assert [r.model_dump() for r in rules] == before_dump
    assert all(any(item is r for r in rules) for item in first)


# T-13 (no I/O part)
def test_selection_does_no_io(monkeypatch):
    a = _rule("opportunity-attack", "Opportunity Attack", "A creature leaves your reach.")

    def _no_open(*args, **kwargs):
        raise AssertionError("select_rules must not open files")

    monkeypatch.setattr(builtins, "open", _no_open)
    assert select_rules("opportunity attack", [a], 6000) == [a]
