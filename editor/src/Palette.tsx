import { useEffect, useMemo, useRef, useState } from "react"
import { icons } from "./icons"

export type Command = { id: string; label: string; group: string; hint?: string; run: () => void }

export function Palette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("")
  const [index, setIndex] = useState(0)
  const list = useRef<HTMLUListElement>(null)
  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    return commands.filter((command) => {
      const text = `${command.group} ${command.label}`.toLowerCase()
      return words.every((word) => text.includes(word))
    })
  }, [commands, query])
  const active = Math.min(index, Math.max(0, shown.length - 1))

  useEffect(() => {
    list.current?.querySelector(".active")?.scrollIntoView({ block: "nearest" })
  }, [active])

  return (
    <div className="scrim" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-label="Commands" onMouseDown={(event) => event.stopPropagation()}>
        <label className="palette-input">
          {icons.search}
          <input
            autoFocus
            value={query}
            placeholder="Go to a shot or thread, or run a command"
            aria-label="Search commands"
            onChange={(event) => {
              setQuery(event.target.value)
              setIndex(0)
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault()
                const delta = event.key === "ArrowDown" ? 1 : -1
                setIndex((active + delta + shown.length) % Math.max(1, shown.length))
              } else if (event.key === "Enter" && shown[active]) {
                event.preventDefault()
                onClose()
                shown[active].run()
              } else if (event.key === "Escape") {
                onClose()
              }
            }}
          />
        </label>
        <ul ref={list}>
          {shown.map((command, position) => (
            <li key={command.id}>
              {position === 0 || shown[position - 1].group !== command.group ? <h3>{command.group}</h3> : null}
              <button
                className={position === active ? "active" : ""}
                onMouseMove={() => setIndex(position)}
                onClick={() => {
                  onClose()
                  command.run()
                }}
              >
                <span>{command.label}</span>
                {command.hint ? <kbd>{command.hint}</kbd> : null}
              </button>
            </li>
          ))}
          {shown.length === 0 ? <li className="empty-note">Nothing matches.</li> : null}
        </ul>
      </div>
    </div>
  )
}
