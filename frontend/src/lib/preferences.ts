// Per-browser UI preferences. Storage errors (private mode, quota) fall back to defaults.

const NARRATIVE_ONLY_KEY = 'vox.narrative_only'

export function loadNarrativeOnly(): boolean {
  try {
    return localStorage.getItem(NARRATIVE_ONLY_KEY) === '1'
  } catch {
    return false
  }
}

export function saveNarrativeOnly(value: boolean): void {
  try {
    localStorage.setItem(NARRATIVE_ONLY_KEY, value ? '1' : '0')
  } catch {
    // Persistence is best-effort; the toggle still works for this page load.
  }
}
