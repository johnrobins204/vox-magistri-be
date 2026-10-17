# Playboard Design Brief (Sprint: React D&D Playboard)

Date: 2026-10-17. Status: working draft, informs the frontend playboard increment.

## Research sources

| Product | What players love | What we take |
|---|---|---|
| **D&D Beyond** | Clean card-based character sheet; ability scores as bold readable badges; red brand accent on light parchment; "every adventure starts with a character" | Character rail with ability-score badges; sheet-like card structure |
| **Roll20** | Chat log as the social heart; dice rolls render inline in chat with formula breakdowns; macro bar for one-click rolls | Rolls as first-class cards inside the narrative log, not a separate panel |
| **Foundry VTT** | Dark theme with gold/brass accents; right-rail tabs (chat, combat, actors); bottom hotbar; scene framing up top | Dark "candlelit" theme, brass trim, right rail for tools, scene bar |
| **TaleSpire** | Warm torchlit diorama feel; physical-feeling dice; atmosphere over chrome | Warm palette (amber/brass on deep brown-black), tactile dice buttons |
| **Baldur's Gate 3** | Ornate serif display type; character portraits with HP always visible; the d20 skill-check moment is theatrical | Serif display headers (Cinzel), persistent portrait + HP, big dramatic roll result |

## Design principles for our playboard

1. **The narrative log is the game.** Solo player + AI DM means the chronicle *is* the
   play surface. It gets center stage, generous typography (bookish serif), and the
   DM's voice reads like a printed adventure module.
2. **Dark, candlelit, warm.** All the beloved *in-play* experiences (Foundry, BG3,
   TaleSpire) are dark; only management tools (D&D Beyond) are light. Deep warm
   charcoal, parchment text, brass accents, oxblood for danger.
3. **Dice are one click away and their results are events.** A dice tray on the right
   rail; results land in the log as dramatic roll cards (big total, formula detail),
   powered by the existing `/roll` slash tool — no backend change.
4. **The hero is always on screen.** Left rail: portrait placeholder, HP bar, the six
   ability scores, condition chips. Stub data now; REQ-0015 (campaign domain) owns
   real characters later.
5. **Atmosphere frames everything.** A slim scene bar up top carries the session,
   model status, and queue — the "table feel" layer.

## Layout

```
┌─────────────────────────── Scene Bar ───────────────────────────┐
│ Character Rail │        Narrative Log (center)     │ Dice Tray  │
│  portrait      │   DM entries: parchment cards     │  d4..d100  │
│  HP bar        │   Player entries: inset, italic   │  adv/dis   │
│  abilities     │   Roll results: dramatic cards    │  custom    │
│  conditions    │                                   │  status    │
├──────────────────────── Composer (full width) ──────────────────┤
```

## Design tokens

- Fonts: Cinzel (display/headers), Alegreya (narrative body), Space Grotesk (UI chrome), IBM Plex Mono (ids/stats)
- Palette: bg `#0e0c0a`, panel `#1a1510`, parchment `#e8dcc4`, muted `#9a8b70`,
  brass `#c8a46e`, brass-bright `#e6c88a`, oxblood `#b3402e`, vitality `#7a9e5f`

## Sprint scope (this increment)

- Theme overhaul (dark candlelit) + playboard grid layout
- Component split: `SceneBar`, `CharacterPanel` (stub), `DiceTray`, `NarrativeLog`, `Composer`
- Dice tray sends `/roll <expr>` through the existing WS message path; roll replies
  (`meta.tool === 'roll'`) render as roll cards
- No backend changes; no real character data (stub, clearly marked)

## Explicitly later

- Real character data / campaign domain (REQ-0015), combat tracker, maps/tokens,
  streaming narration (REQ-0007), multi-player, audio/ambience
