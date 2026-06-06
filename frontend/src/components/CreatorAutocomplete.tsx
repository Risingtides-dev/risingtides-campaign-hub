import { useState, useRef, useEffect, useCallback } from "react"
import { Input } from "@/components/ui/input"
import { useCreators } from "@/lib/queries"

interface CreatorAutocompleteProps {
  value: string
  onChange: (value: string) => void
  onSelect?: (username: string) => void
  onBlur?: () => void
  placeholder?: string
  className?: string
}

export function CreatorAutocomplete({
  value,
  onChange,
  onSelect,
  onBlur,
  placeholder = "@username",
  className,
}: CreatorAutocompleteProps) {
  const [open, setOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const { data: creators } = useCreators()

  const query = value.replace(/^@/, "").toLowerCase().trim()

  const filtered =
    query.length > 0 && creators
      ? creators
          .filter((c) => c.username.toLowerCase().includes(query))
          .slice(0, 8)
      : []

  const showDropdown = open && filtered.length > 0

  const selectCreator = useCallback(
    (username: string) => {
      onChange(username)
      onSelect?.(username)
      setOpen(false)
      setHighlightIdx(-1)
    },
    [onChange, onSelect],
  )

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [])

  // Scroll highlighted item into view
  useEffect(() => {
    if (highlightIdx >= 0 && listRef.current) {
      const item = listRef.current.children[highlightIdx] as HTMLElement
      item?.scrollIntoView({ block: "nearest" })
    }
  }, [highlightIdx])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showDropdown) return

    if (e.key === "ArrowDown") {
      e.preventDefault()
      setHighlightIdx((i) => (i < filtered.length - 1 ? i + 1 : 0))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setHighlightIdx((i) => (i > 0 ? i - 1 : filtered.length - 1))
    } else if (e.key === "Enter" && highlightIdx >= 0) {
      e.preventDefault()
      selectCreator(filtered[highlightIdx].username)
    } else if (e.key === "Escape") {
      setOpen(false)
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
      <Input
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
          setHighlightIdx(-1)
        }}
        onFocus={() => {
          if (query.length > 0) setOpen(true)
        }}
        onBlur={() => {
          // Delay to allow click on dropdown item
          setTimeout(() => {
            setOpen(false)
            onBlur?.()
          }, 150)
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className={className}
        autoComplete="off"
      />
      {showDropdown && (
        <div
          ref={listRef}
          className="absolute z-50 top-full left-0 mt-1 w-full max-h-[200px] overflow-y-auto rounded-md border border-white/8 bg-rt-bg-card shadow-lg"
        >
          {filtered.map((creator, idx) => (
            <button
              key={creator.username}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                selectCreator(creator.username)
              }}
              onMouseEnter={() => setHighlightIdx(idx)}
              className={`w-full text-left px-3 py-1.5 text-[13px] cursor-pointer transition-colors ${
                idx === highlightIdx
                  ? "bg-white/[0.03] text-rt-magenta"
                  : "text-rt-fg hover:bg-white/[0.03]"
              }`}
            >
              <span className="font-semibold">@{creator.username}</span>
              {creator.campaigns_count > 0 && (
                <span className="ml-2 text-[11px] text-rt-fg-tertiary">
                  {creator.campaigns_count} campaign{creator.campaigns_count !== 1 ? "s" : ""}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
