import { useEffect, useMemo, useState } from 'react'
import type { Species } from '../types'

interface SpeciesBrowserProps {
  species: Species[]
  onPick: (species: Species) => void
  onClose: () => void
}

type Group = '5.5e' | '5e' | 'third-party'
type EditionFilter = 'all' | Group

const FILTERS: { key: EditionFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: '5.5e', label: '5.5e' },
  { key: '5e', label: '5e' },
  { key: 'third-party', label: 'Third-party' },
]

const GROUPS: { key: Group; heading: string }[] = [
  { key: '5.5e', heading: '5.5e' },
  { key: '5e', heading: '5e' },
  { key: 'third-party', heading: 'Third-party' },
]

function groupOf(species: Species): Group | null {
  return species.third_party ? 'third-party' : species.edition
}

function inFilter(species: Species, filter: EditionFilter): boolean {
  return filter === 'all' || groupOf(species) === filter
}

export function SpeciesBrowser({ species, onPick, onClose }: SpeciesBrowserProps) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<EditionFilter>('all')

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [onClose])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return species.filter((s) => inFilter(s, filter) && s.name.toLowerCase().includes(needle))
  }, [species, query, filter])

  const groups = GROUPS.map((g) => ({
    ...g,
    items: visible.filter((s) => groupOf(s) === g.key),
  })).filter((g) => g.items.length > 0)

  return (
    <div
      className="modal-backdrop"
      onClick={(event) => {
        event.stopPropagation()
        onClose()
      }}
    >
      <div
        className="modal panel species-browser"
        role="dialog"
        aria-modal="true"
        aria-label="Species Browser"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <span className="modal-icon" aria-hidden="true">
            ❧
          </span>
          <h2>Species Browser</h2>
          <span className="species-count">
            {visible.length} of {species.length}
          </span>
          <button type="button" className="ghost modal-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="species-toolbar">
          <label className="field">
            <span>Search by name</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Aasimar"
              maxLength={40}
              autoFocus
            />
          </label>
          <div className="species-filters" role="group" aria-label="Filter by edition">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className="species-filter"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
                <span className="species-filter-count">{species.filter((s) => inFilter(s, f.key)).length}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="species-scroll">
          {species.length === 0 ? (
            <p className="empty">No species on file.</p>
          ) : groups.length === 0 ? (
            <p className="empty">No species match.</p>
          ) : (
            groups.map((g) => (
              <section key={g.key} className="species-group">
                <h3 className="creator-section">
                  {g.heading} · {g.items.length}
                </h3>
                <ul className="species-cards">
                  {g.items.map((s) => (
                    <li key={s.id}>
                      <article className="species-card">
                        <div className="species-card-head">
                          <h4 className="species-card-name">{s.name}</h4>
                          {s.edition ? <span className="badge">{s.edition}</span> : null}
                          {s.third_party ? <span className="badge third-party">Third-party</span> : null}
                        </div>
                        <p className="species-meta">
                          {s.source}
                          {s.publisher ? <> · {s.publisher}</> : null}
                          {' · '}
                          {s.creature_type}
                        </p>
                        <p className="species-card-desc">{s.description}</p>
                        <p className="species-card-impl">
                          <span>Creation</span>
                          {s.character_creation_implications}
                        </p>
                        <div className="species-card-actions">
                          <button type="button" onClick={() => onPick(s)}>
                            Use this species
                          </button>
                        </div>
                      </article>
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
