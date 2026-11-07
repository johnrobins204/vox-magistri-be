---
name: feature-priorities
description: "Assess vox-magistri-be's maturity and recommend the next feature priorities by interviewing the owner and scoring the backlog against evidence. Use when asked 'what should we build next', 'prioritise the backlog', 'roadmap', 'feature priorities', or 'what is the app missing'."
---

# Feature priorities (token-lean)

Goal: a ranked, evidence-grounded shortlist of the next 1-3 requirements, chosen with
the owner, not for them. The project is a solo, part-time hobby app built for the
author's children (`docs/constraints.md`): fun and playability beat hardening.

## Rules
- Do not read specs, ADRs, `BACKLOG.json`, or `LOG.md`. Use `scripts/backlog.py`.
- Ground every claim in a fact from step 1; mark anything unverified as such.
- Interview with `ask_user`, one focused form per topic (max 4 forms). Offer enum
  options drawn from real backlog items, never open-ended "what do you want?".
- Do not implement anything. Output is a recommendation; new work goes through the
  Coworking Orchestrator (`/new-req`).

## Step 1: Evidence snapshot (about 5 tool calls)
1. `python scripts/backlog.py list` and `show` for any `in_progress` item (its tasks
   and follow-ups are the freshest debt list).
2. `git log --oneline -15` for recent direction.
3. Capability inventory, by listing only: `ls app/intelligence/tools frontend/src/components
   app/reference`, and the route list via `grep -n "@router" app/api/v1/*.py`.
4. Reality checks that decide maturity: does the DM remember beyond the recent-turn
   window (REQ-0021)? Is inference streamed (REQ-0007)? Is there a campaign/quest/scene
   model (REQ-0015)? Do dice use the character (REQ-0022)? Can a non-author run it
   (auth/CORS/startup, REQ-0009/0011)?
5. Summarise as a maturity table: Area | State (works / partial / missing) | Evidence.
   Areas: Play loop, DM quality and memory, Rules and dice, Characters, Campaign and
   world, Frontend UX, Reliability and latency, Onboarding/sharing, Dev workflow.

## Step 2: Interview (ground it in the table)
Show the maturity table first, then ask, in order:
1. **Outcome**: what should a play session feel like in the next month (one pick)?
   e.g. "kids play a full evening unaided", "a coherent multi-session campaign",
   "rules-accurate combat", "polish and look".
2. **Pain**: the single biggest friction in the last session played, and which options
   from the table it maps to. Include "haven't played enough to know".
3. **Constraints**: hours per week, hardware/model latency tolerance, who plays
   (ages, devices, same room or remote), any date to hit.
4. **Appetite**: for each candidate, "fun to build" vs "chore" (multi-select), so
   fun/learning weight (constraint 5) is real input, not a guess.
Skip a question when step 1 already answers it; say so.

## Step 3: Score and rank
Candidates = open backlog items plus up to 3 gaps found in step 1 that have no REQ.
Score each 1-5 on: Player impact (from interview), Unblocks other work, Effort
(inverse), Risk/reversibility, Fun to build. Weight player impact and fun highest,
effort next, then the rest. Show a table with one-line justifications and the weighted
total. Drop items superseded or marked not-to-execute (e.g. REQ-0010).

## Step 4: Recommendation (under 40 lines)
- Top 3, in order, each with: why now, what it unblocks, size (S/M/L), and the single
  riskiest assumption.
- What to defer and why; what to drop or merge (stale backlog entries).
- A "next step" line: the exact `/new-req` sentence to start the first one.
- Offer to record the ranking: the owner decides, then use `scripts/backlog.py` to
  re-order or annotate (`add-task`, `followup`) only if asked.
