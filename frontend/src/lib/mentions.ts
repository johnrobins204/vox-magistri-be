/**
 * Entity mention matcher for chat text (SPEC-0022, REQ-0036, ADR-0016, PAT-ARCH-014).
 *
 * Mirrors the server rule in `app/intelligence/world_mentions.py`: `_tokens` (casefolded
 * `[a-z0-9]+` runs) and `_known_labels` (name + aliases). Change both together.
 * Pure: no React, no DOM, no logging, no state.
 */
import type { WorldEntity } from '../types'

export interface Segment {
  text: string
  entity?: WorldEntity
}

interface Hit {
  start: number
  end: number
  entity: WorldEntity
}

/** Lowercase `[a-z0-9]+` runs of a label (server `_tokens`). */
function tokensOf(label: string): string[] {
  return label.toLowerCase().match(/[a-z0-9]+/g) ?? []
}

/** Every occurrence of every non-rejected entity label, in entity list order. */
function collectHits(text: string, entities: WorldEntity[]): Hit[] {
  const hits: Hit[] = []
  for (const entity of entities) {
    if (entity.status === 'rejected') continue
    for (const label of [entity.name, ...entity.aliases]) {
      const tokens = tokensOf(label)
      if (tokens.length === 0) continue
      // Tokens in order, joined by a non-empty non-alphanumeric run; alphanumeric boundaries.
      const pattern = new RegExp(`(?<![a-z0-9])${tokens.join('[^a-z0-9]+')}(?![a-z0-9])`, 'gi')
      for (const match of text.matchAll(pattern)) {
        const start = match.index ?? 0
        hits.push({ start, end: start + match[0].length, entity })
      }
    }
  }
  return hits
}

/**
 * Splits `text` into contiguous segments; marked segments carry the matched entity.
 * Joining every `text` value yields `text` exactly. Longest match wins; overlaps dropped.
 */
export function segmentText(text: string, entities: WorldEntity[]): Segment[] {
  // Array.prototype.sort is stable, so equal-length, equal-start ties keep entity list order.
  const candidates = collectHits(text, entities).sort(
    (a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start,
  )
  const kept: Hit[] = []
  for (const hit of candidates) {
    if (kept.every((k) => hit.end <= k.start || k.end <= hit.start)) kept.push(hit)
  }
  kept.sort((a, b) => a.start - b.start)

  const segments: Segment[] = []
  let cursor = 0
  for (const hit of kept) {
    if (hit.start > cursor) segments.push({ text: text.slice(cursor, hit.start) })
    segments.push({ text: text.slice(hit.start, hit.end), entity: hit.entity })
    cursor = hit.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) })
  return segments.length > 0 ? segments : [{ text }]
}
