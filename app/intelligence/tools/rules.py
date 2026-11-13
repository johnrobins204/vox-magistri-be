"""
`/rules` tool (SPEC-0014 WP-2 and WP-7; ADR-0009, PAT-ARCH-009).

`select_rules` is pure: stdlib only, no I/O, no logging, no mutation of its arguments.
`run` selects from `context["reference"]["rules"]` (the in-memory catalog loaded at startup),
builds the rules consult prompt and makes exactly one `generate` call. It never touches the
store, never writes messages, and logs counts only.
"""

import asyncio
import inspect
import re
from collections.abc import Sequence
from typing import Any

from app.config import get_settings
from app.intelligence.embeddings import cosine_similarity
from app.intelligence.prompt_builders import build_rules_prompt
from app.intelligence.tools import ToolError
from app.intelligence.tools.query_expansion import expand_query_for_5e
from app.reference.rules import Rule
from app.services.logger import get_logger

logger = get_logger(__name__)

NAME = "rules"
DESCRIPTION = "Look up a rule from the rules reference."

_USAGE = "Usage: /rules <your rules question>"
TRAINING_DISCLAIMER = "Not checked against the SRD rules text."

MAX_RULES = 3
NAME_WEIGHT = 3
TEXT_WEIGHT = 1
MIN_SCORE = 3

# 2024 (5.5e) first on ties; anything else ranks 2.
_EDITION_RANK = {"5.5e": 0, "5e": 1}

_STOPWORDS = frozenset(
    """
    a an the and or of to in on at for with from by is are was were be been am do does did
    can could should would will may might how what when where which who whom why if it its i me
    my you your he she they them their we us our this that these those as not no any there rule
    rules work works happen happens also about into than then so just get gets
    """.split()
)


def _fold(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_fold(word) for word in words if len(word) >= 2 and word not in _STOPWORDS}


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()



def select_rules(question: str, rules: Sequence[Rule], budget_chars: int, query_vector: list[float] | None = None) -> list[Rule]:
    """
    Hybrid Retrieval: Merges Lexical (keyword) and Semantic (vector) scores.
    Matches the Min-Max normalization and weighted merge from the C# architecture.
    """
    q = _tokens(question)
    if not q or not rules or budget_chars <= 0:
        return []

    # --- 1. Calculate Raw Scores ---
    raw_results = []
    for rule in rules:
        # Lexical (Keyword) Scoring
        name_tokens = _tokens(rule.name)
        name_hits = len(q & name_tokens)
        text_hits = len((q - name_tokens) & _tokens(rule.description))
        lexical_score = float(NAME_WEIGHT * name_hits + TEXT_WEIGHT * text_hits)

        # Semantic (Vector) Scoring
        vector_score = 0.0
        if query_vector and rule.vector:
            vector_score = cosine_similarity(query_vector, rule.vector)

        raw_results.append({"rule": rule, "lexical": lexical_score, "vector": vector_score})

    # --- 2. Min-Max Normalization (Matches C# `vecRange` logic) ---
    lex_max = max(r["lexical"] for r in raw_results) if raw_results else 0
    lex_min = min(r["lexical"] for r in raw_results) if raw_results else 0
    lex_range = lex_max - lex_min

    vec_max = max(r["vector"] for r in raw_results) if raw_results else 0
    vec_min = min(r["vector"] for r in raw_results) if raw_results else 0
    vec_range = vec_max - vec_min

    scored = []
    for r in raw_results:
        # Normalize to 0.0 - 1.0
        norm_lex = (
            (r["lexical"] - lex_min) / lex_range
            if lex_range > 0
            else (1.0 if r["lexical"] > 0 else 0.0)
        )
        norm_vec = (
            (r["vector"] - vec_min) / vec_range
            if vec_range > 0
            else (1.0 if r["vector"] > 0 else 0.0)
        )

        # Merge Weights: 40% Keyword, 60% Vector (Adjustable)
        hybrid_score = (norm_lex * 0.4) + (norm_vec * 0.6)

        # Apply the equivalent of your MIN_SCORE threshold against the hybrid scale
        # (Assuming 0.3 out of 1.0 is a decent baseline relevance)
        if hybrid_score >= 0.3 or r["lexical"] >= MIN_SCORE:
            scored.append((hybrid_score, r["rule"]))

    # --- 3. Sort, Deduplicate, and Pack ---
    # Sort by hybrid score, then edition rank
    scored.sort(
        key=lambda item: (-item[0], _EDITION_RANK.get(item[1].edition, 2), item[1].id),
    )

    seen: set[str] = set()
    ranked: list[Rule] = []
    for _score, rule in scored:
        key = _name_key(rule.name)
        if key in seen:
            continue
        seen.add(key)
        ranked.append(rule)

    if not ranked or len(ranked[0].description) > budget_chars:
        return []

    chosen: list[Rule] = []
    used = 0
    for rule in ranked:
        if len(chosen) >= MAX_RULES:
            break
        size = len(rule.description)
        if used + size > budget_chars:
            continue
        chosen.append(rule)
        used += size

    return chosen


def run(args: str, context: dict) -> dict[str, Any]:
    question = (args or "").strip()
    if not question:
        raise ToolError(_USAGE)

    reference = context.get("reference")
    catalog = reference.get("rules") if isinstance(reference, dict) else None
    catalog = catalog or []

    budget = get_settings().prompts.rules_budget_chars

    # ---------------------------------------------------------
    # NEW QUERY EXPANSION LOGIC
    # ---------------------------------------------------------
    try:
        inference_service = context.get("inference")
        ollama_client = getattr(inference_service, "client", None)
        
        if inference_service and ollama_client:
            # Call expand_query_for_5e using the project's client
            expanded_terms = asyncio.run(expand_query_for_5e(question, client=ollama_client))
        else:
            expanded_terms = []
            
        if expanded_terms:
            logger.info(f"Expanded /rules query with terms: {expanded_terms}")
            combined_question = question + " " + " ".join(expanded_terms)
        else:
            combined_question = question
    except Exception as e:
        logger.error(f"Query expansion failed, using original query: {e}")
        combined_question = question
    # ---------------------------------------------------------

    # Pass the combined question string into the pure select_rules function
    chosen = select_rules(combined_question, catalog, budget)

    excerpts = [{"name": r.name, "edition": r.edition, "text": r.description} for r in chosen]
    prompt = build_rules_prompt(question, excerpts)
    reply = context["inference"].generate(prompt)

    if chosen:
        source = "rules"
        text = reply
    else:
        source = "training"
        text = reply.rstrip() + "\n\n" + TRAINING_DISCLAIMER

    logger.info(
        "rules.consulted",
        extra={
            "source": source,
            "rule_count": len(chosen),
            "excerpt_chars": sum(len(r.description) for r in chosen),
        },
    )
    return {
        "text": text,
        "meta": {"tool": NAME, "source": source, "rule_ids": [r.id for r in chosen]},
    }
