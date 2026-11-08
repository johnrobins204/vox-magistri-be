import type { ToolInfo } from '../types'

/**
 * Text after the leading "/" when the draft is a slash token (no whitespace yet),
 * otherwise null. "/" alone yields "".
 */
export function slashQuery(draft: string): string | null {
  if (!draft.startsWith('/')) return null
  const query = draft.slice(1)
  if (/\s/.test(query)) return null
  return query
}

/** Case-insensitive name-prefix match. Empty query returns all; backend order is kept. */
export function filterTools(tools: ToolInfo[], query: string): ToolInfo[] {
  const q = query.toLowerCase()
  if (q === '') return tools
  return tools.filter((tool) => tool.name.toLowerCase().startsWith(q))
}

// ADR-0014 (accepted): selecting a tool inserts "/name ". Change only here.
export function applyToolSelection(tool: ToolInfo, _draft: string): string {
  return `/${tool.name} `
}
