import type { ToolInfo } from '../types'

interface SlashPickerProps {
  tools: ToolInfo[]
  activeIndex: number
  onSelect: (tool: ToolInfo) => void
  onHover: (index: number) => void
}

export function SlashPicker({ tools, activeIndex, onSelect, onHover }: SlashPickerProps) {
  return (
    <ul role="listbox" id="slash-picker" className="slash-picker">
      {tools.map((tool, i) => (
        <li
          key={tool.name}
          role="option"
          aria-selected={i === activeIndex}
          className={i === activeIndex ? 'slash-picker-row active' : 'slash-picker-row'}
          onMouseDown={(e) => {
            // Keep textarea focus so the composer stays active after a click.
            e.preventDefault()
            onSelect(tool)
          }}
          onMouseEnter={() => onHover(i)}
        >
          <span className="slash-picker-name">/{tool.name}</span>
          <span className="slash-picker-desc">{tool.description}</span>
        </li>
      ))}
    </ul>
  )
}
