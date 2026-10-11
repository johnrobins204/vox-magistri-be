# Project Constraints & Engineering Charter (vox-magistri-be)

Decision drivers consulted by the senior-architect agent for every rubric it builds.
Requirements below use RFC 2119 keywords (MUST, MUST NOT, SHOULD, SHOULD NOT, MAY).

## Project context
- This is a solo, part-time hobby project built by one developer for their children.
- There is MUST NOT be an assumption of productionization, multi-tenancy, scale, or
  compliance needs unless the human explicitly states one.

## Standing constraints
1. Engineering decisions MUST favor the smallest edit that satisfies the requirement
   over broader refactors, unless the broader change is the explicit requirement.
2. Code and architecture SHOULD favor modularity and reusability, but MUST NOT
   introduce abstraction speculatively (no new abstraction layer without at least
   two concrete call sites).
3. New runtime dependencies MUST be justified against the existing stack (FastAPI,
   httpx, pydantic, uvicorn, Ollama) — SHOULD avoid adding one where stdlib or an
   existing dependency already suffices.
4. Every reusable architecture, spec, or code pattern MUST be recorded in
   `docs/patterns/` before or immediately after first use (see
   [docs/patterns/README.md](./patterns/README.md)).
5. Fun and learning value for the author SHOULD be weighted as a legitimate rubric
   criterion, on par with maintainability.

## Default rubric dimensions
Senior-architect MAY add requirement-specific dimensions; these are the standing defaults.

| Dimension | Weight | Notes |
|---|---|---|
| Simplicity / smallest-edit fit | High | solo dev, part-time |
| Reversibility | High | low stakes, keep options open |
| Maintainability for one part-time person | High | |
| Reuse of existing patterns/dependencies | Medium | |
| Fun / learning value | Medium | explicit per constraint 5 |
| Performance / scalability | Low | explicitly de-prioritized |
| Security hardening beyond sane defaults | Low | no production intent |

## Non-negotiables
- Never expand scope toward production-grade hardening (auth hardening beyond the
  existing dev token, horizontal scaling, multi-tenant isolation, etc.) unless the
  human explicitly asks for it.
- Every architect/spec-writer/developer step MUST consult `docs/patterns/` before
  producing new architecture, specs, or code for this project.
