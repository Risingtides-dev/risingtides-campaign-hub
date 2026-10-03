import { useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Check, Plus, Search } from "lucide-react"
import type { LibraryNiche } from "@/lib/types"

/**
 * Searchable niche picker.
 *
 * Stays open while you click, because tagging a creator usually means
 * applying two or three tags and reopening a popover each time is what
 * made the old flow unusable. Anything typed that doesn't already exist
 * can be created inline — that is the whole point of a vocabulary that
 * lives in the database rather than in a source file.
 *
 * Rendered in a portal so it escapes the scroll and overflow contexts of
 * whichever card triggered it.
 */
export interface NichePickerProps {
  anchor: HTMLElement | null
  niches: LibraryNiche[]
  /** Names currently on the target. Empty in bulk mode. */
  selected: string[]
  onToggle: (name: string) => void
  onCreate: (name: string) => void
  onClose: () => void
  /** Bulk mode adds rather than toggles, so nothing reads as "selected". */
  mode?: "single" | "bulk"
}

const WIDTH = 320
const MAX_HEIGHT = 380
const GAP = 6

export function NichePicker({
  anchor,
  niches,
  selected,
  onToggle,
  onCreate,
  onClose,
  mode = "single",
}: NichePickerProps) {
  const [query, setQuery] = useState("")
  const popRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Close on outside click or Escape. The anchor is excluded so the button
  // that opened the picker can also close it without double-firing.
  useEffect(() => {
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node
      if (popRef.current?.contains(target)) return
      if (anchor?.contains(target)) return
      onClose()
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener("mousedown", onPointerDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onPointerDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [anchor, onClose])

  const position = useMemo(() => {
    if (!anchor) return { top: 0, left: 0 }
    const rect = anchor.getBoundingClientRect()
    return {
      top: Math.min(rect.bottom + GAP, window.innerHeight - MAX_HEIGHT - 12),
      left: Math.max(12, Math.min(rect.left, window.innerWidth - WIDTH - 12)),
    }
  }, [anchor])

  const needle = query.trim().toLowerCase()
  const matches = useMemo(
    () => niches.filter((n) => n.name.includes(needle)),
    [niches, needle]
  )
  const exact = matches.some((n) => n.name === needle)
  const selectedSet = useMemo(() => new Set(selected), [selected])

  function submitCreate() {
    if (!needle || exact) return
    onCreate(needle)
    setQuery("")
  }

  return createPortal(
    <div
      ref={popRef}
      role="dialog"
      aria-label="Choose niches"
      style={{ top: position.top, left: position.left, width: WIDTH }}
      className="fixed z-[120] overflow-hidden rounded-xl border border-white/15 bg-rt-bg-elevated shadow-2xl"
    >
      <div className="border-b border-white/10 p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-rt-fg-tertiary" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                if (!exact && needle) submitCreate()
                else if (matches.length === 1) onToggle(matches[0].name)
              }
            }}
            placeholder="Search or create a niche…"
            className="w-full rounded-lg border border-white/10 bg-rt-bg-card py-2 pl-9 pr-3 text-[13px] text-rt-fg placeholder:text-rt-fg-tertiary focus:border-rt-magenta focus:outline-none"
          />
        </div>
      </div>

      <div className="max-h-[264px] overflow-y-auto p-1.5">
        {matches.length === 0 ? (
          <p className="px-3 py-6 text-center text-[12.5px] text-rt-fg-tertiary">
            No niche matches “{query.trim()}”.
            <br />
            Create it below.
          </p>
        ) : (
          matches.map((niche) => {
            const on = mode === "single" && selectedSet.has(niche.name)
            return (
              <button
                key={niche.id}
                type="button"
                onClick={() => onToggle(niche.name)}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-rt-bg-card"
              >
                <span
                  className={`grid size-4 shrink-0 place-items-center rounded border ${
                    on
                      ? "border-transparent bg-rt-magenta text-white"
                      : "border-white/20"
                  }`}
                >
                  {on && <Check className="size-3" />}
                </span>
                <span className="flex-1 truncate text-[13px] text-rt-fg">
                  {niche.name}
                </span>
                <span className="tabular-nums text-[11px] text-rt-fg-tertiary">
                  {niche.count}
                </span>
              </button>
            )
          })
        )}
      </div>

      {needle && !exact && (
        <div className="border-t border-white/10 p-1.5">
          <button
            type="button"
            onClick={submitCreate}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-rt-fg-secondary transition-colors hover:bg-rt-bg-card hover:text-rt-fg"
          >
            <span className="grid size-4 shrink-0 place-items-center rounded bg-rt-magenta text-white">
              <Plus className="size-3" />
            </span>
            <span>
              Create <span className="font-semibold text-rt-fg">“{needle}”</span>
            </span>
          </button>
        </div>
      )}
    </div>,
    document.body
  )
}
