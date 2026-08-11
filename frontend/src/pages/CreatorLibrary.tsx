import { useMemo, useState } from "react"
import { toast } from "sonner"
import { Loader2, Plus, RefreshCw, Search, Settings2, X } from "lucide-react"
import {
  useApplyNiche,
  useLibrary,
  useNiches,
  useRefreshLibraryStats,
  useSetLibraryNiches,
} from "@/lib/queries"
import {
  LIBRARY_WINDOW_LABELS,
  type LibraryCreator,
  type LibraryWindow,
} from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NichePicker } from "@/components/library/NichePicker"
import { avatarStyle, initials, nicheStyle } from "@/components/library/nicheColors"
import { CreatorDrawer } from "@/components/library/CreatorDrawer"
import { NicheManager } from "@/components/library/NicheManager"
import { AddCreatorDialog } from "@/components/library/AddCreatorDialog"

const WINDOWS: LibraryWindow[] = ["w30", "w60", "w90", "wall"]

type SortKey = "pcpm" | "total" | "median" | "viral" | "rate" | "name"

const SORT_LABELS: Record<SortKey, string> = {
  pcpm: "Projected CPM (best value)",
  total: "Most views in window",
  median: "Typical views",
  viral: "Viral rate",
  rate: "Cheapest rate",
  name: "Username",
}

function compact(value: number | null | undefined): string {
  if (!value) return "—"
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`
  return String(value)
}

/** Jake's thresholds: under $1 excellent, $1-2 good, over $3 needs attention. */
function cpmTone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-rt-fg-tertiary"
  if (value < 1) return "text-rt-green"
  if (value <= 2) return "text-rt-amber"
  return "text-rt-red"
}

export default function CreatorLibrary() {
  const [window_, setWindow] = useState<LibraryWindow>("w60")
  const [query, setQuery] = useState("")
  const [selectedNiches, setSelectedNiches] = useState<string[]>([])
  const [logic, setLogic] = useState<"any" | "all">("any")
  const [untaggedOnly, setUntaggedOnly] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>("pcpm")
  const [tagMode, setTagMode] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [openCreator, setOpenCreator] = useState<string | null>(null)
  const [showManager, setShowManager] = useState(false)
  const [showAdd, setShowAdd] = useState(false)

  // Which element the niche picker hangs off, and what it's tagging.
  const [picker, setPicker] = useState<
    | { anchor: HTMLElement; mode: "filter" }
    | { anchor: HTMLElement; mode: "single"; username: string }
    | { anchor: HTMLElement; mode: "bulk" }
    | null
  >(null)

  const { data, isLoading, isError, error } = useLibrary(window_)
  const { data: nicheData } = useNiches()
  const setNiches = useSetLibraryNiches()
  const applyNiche = useApplyNiche()
  const refreshStats = useRefreshLibraryStats()

  const creators = useMemo(() => data?.creators ?? [], [data])
  const niches = useMemo(() => nicheData?.niches ?? [], [nicheData])

  const taggedCount = creators.filter((c) => c.niches.length > 0).length
  const untaggedCount = creators.length - taggedCount

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    let out = creators.filter((c) => {
      if (needle && !c.username.toLowerCase().includes(needle)) return false
      if (untaggedOnly && c.niches.length > 0) return false
      if (selectedNiches.length === 0) return true
      return logic === "all"
        ? selectedNiches.every((n) => c.niches.includes(n))
        : selectedNiches.some((n) => c.niches.includes(n))
    })

    const stat = (c: LibraryCreator) => c.stats?.[window_] ?? null
    // Creators with no data sort last on every measure — an unknown CPM
    // must never read as the cheapest option on the page.
    const missingLast = (value: number | null | undefined, asc: boolean) =>
      value === null || value === undefined
        ? Number.POSITIVE_INFINITY
        : asc
          ? value
          : -value

    out = [...out].sort((a, b) => {
      switch (sortKey) {
        case "pcpm":
          return missingLast(stat(a)?.pcpm, true) - missingLast(stat(b)?.pcpm, true)
        case "total":
          return missingLast(stat(a)?.total, false) - missingLast(stat(b)?.total, false)
        case "median":
          return missingLast(stat(a)?.median, false) - missingLast(stat(b)?.median, false)
        case "viral":
          return missingLast(stat(a)?.viral_rate, false) - missingLast(stat(b)?.viral_rate, false)
        case "rate":
          return missingLast(a.rate, true) - missingLast(b.rate, true)
        default:
          return a.username.localeCompare(b.username)
      }
    })
    return out
  }, [creators, query, untaggedOnly, selectedNiches, logic, sortKey, window_])

  // Rank numbers only mean something once you've narrowed to a niche.
  const ranked = selectedNiches.length > 0

  function toggleFilterNiche(name: string) {
    setSelectedNiches((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    )
  }

  function togglePicked(key: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function tagOne(creator: LibraryCreator, name: string) {
    const next = creator.niches.includes(name)
      ? creator.niches.filter((n) => n !== name)
      : [...creator.niches, name]
    try {
      await setNiches.mutateAsync({ username: creator.key, niches: next })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save that tag")
    }
  }

  async function bulkTag(name: string) {
    const usernames = [...picked]
    if (usernames.length === 0) return
    const niche = niches.find((n) => n.name === name)
    try {
      // Creating and applying in one step keeps bulk tagging to a single
      // gesture even for a niche that doesn't exist yet.
      const id = niche?.id ?? (await applyNicheByName(name))
      const res = await applyNiche.mutateAsync({ id, usernames })
      toast.success(
        `Tagged ${res.tagged} creator${res.tagged === 1 ? "" : "s"} as “${name}”`
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't apply that niche")
    }
  }

  async function applyNicheByName(name: string): Promise<number> {
    const { api } = await import("@/lib/api")
    const made = await api.createNiche(name)
    return made.id
  }

  const activeCreator = openCreator
    ? creators.find((c) => c.key === openCreator) ?? null
    : null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-rt-fg-tertiary">
        <Loader2 className="mr-2 size-4 animate-spin" /> Loading library…
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-xl border border-rt-red/30 bg-rt-red/5 p-6">
        <p className="font-semibold text-rt-red">Couldn't load the library</p>
        <p className="mt-1 text-[13px] text-rt-fg-tertiary">
          {error instanceof Error ? error.message : "Unknown error"}
        </p>
      </div>
    )
  }

  return (
    <div className="pb-28">
      {/* Header */}
      <div className="flex flex-wrap items-end gap-6 pb-4">
        <div>
          <h1 className="text-[25px] font-semibold tracking-tight text-rt-fg">
            Creator Library
          </h1>
          <p className="mt-1 text-[13px] text-rt-fg-tertiary">
            Every creator you've booked or scouted — tagged, rated and searchable.
          </p>
        </div>
        <div className="ml-auto min-w-[220px]">
          <div className="mb-1.5 flex justify-between text-[11px] text-rt-fg-tertiary">
            <span>Tagging progress</span>
            <span>
              <b className="text-rt-fg">{taggedCount}</b> of{" "}
              <b className="text-rt-fg">{creators.length}</b> tagged
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded bg-rt-bg-elevated">
            <div
              className="h-full rounded bg-gradient-to-r from-rt-magenta to-rt-purple transition-all"
              style={{
                width: `${creators.length ? (taggedCount / creators.length) * 100 : 0}%`,
              }}
            />
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 pb-3.5">
        <div className="relative min-w-[190px] max-w-[290px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-rt-fg-tertiary" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search creators…"
            className="pl-9"
          />
        </div>

        <Button
          variant="outline"
          onClick={(e) =>
            setPicker(
              picker?.mode === "filter"
                ? null
                : { anchor: e.currentTarget, mode: "filter" }
            )
          }
        >
          Filter by niche
          {selectedNiches.length > 0 && (
            <span className="ml-1.5 rounded-full bg-rt-magenta px-1.5 text-[10px] font-bold text-white">
              {selectedNiches.length}
            </span>
          )}
        </Button>

        <Button
          variant={untaggedOnly ? "default" : "outline"}
          onClick={() => setUntaggedOnly((v) => !v)}
        >
          Untagged only
          <span className="ml-1.5 rounded-full bg-rt-bg-elevated px-1.5 text-[10px] font-bold text-rt-fg-tertiary">
            {untaggedCount}
          </span>
        </Button>

        <div className="flex-1" />

        <div className="flex gap-0.5 rounded-lg border border-white/10 bg-rt-bg-card p-0.5">
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWindow(w)}
              className={`rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors ${
                window_ === w
                  ? "bg-rt-bg-elevated font-semibold text-rt-fg"
                  : "text-rt-fg-tertiary hover:text-rt-fg"
              }`}
            >
              {LIBRARY_WINDOW_LABELS[w]}
            </button>
          ))}
        </div>

        <label className="flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-rt-bg-card pl-3 pr-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
            Rank by
          </span>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="cursor-pointer appearance-none bg-transparent py-1 text-[13px] font-semibold text-rt-fg focus:outline-none"
          >
            {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
              <option key={key} value={key} className="bg-rt-bg-elevated">
                {SORT_LABELS[key]}
              </option>
            ))}
          </select>
        </label>

        <Button
          variant={tagMode ? "default" : "outline"}
          onClick={() => {
            setTagMode((v) => !v)
            setPicked(new Set())
          }}
        >
          Tag mode
        </Button>

        <Button variant="outline" onClick={() => setShowManager(true)}>
          <Settings2 className="size-3.5" /> Manage niches
        </Button>

        <Button
          variant="outline"
          disabled={refreshStats.isPending}
          onClick={async () => {
            try {
              const res = await refreshStats.mutateAsync()
              toast.success(
                `Refreshed ${res.creators} creators from ${res.trackers} trackers`
              )
            } catch (e) {
              toast.error(e instanceof Error ? e.message : "Refresh failed")
            }
          }}
        >
          {refreshStats.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw className="size-3.5" />
          )}
          Refresh stats
        </Button>

        <Button onClick={() => setShowAdd(true)}>
          <Plus className="size-3.5" /> Add creator
        </Button>
      </div>

      {/* Active niche filters */}
      {selectedNiches.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pt-3.5">
          <span className="text-[11px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
            Filtering
          </span>
          {selectedNiches.map((name) => (
            <span
              key={name}
              className="flex items-center gap-1.5 rounded-full bg-gradient-to-r from-rt-magenta to-rt-purple py-1 pl-3 pr-2 text-[12px] font-semibold text-white"
            >
              {name}
              <button
                type="button"
                aria-label={`Remove ${name}`}
                onClick={() => toggleFilterNiche(name)}
                className="text-white/75 hover:text-white"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          <div className="flex gap-0.5 rounded-lg border border-white/10 bg-rt-bg-elevated p-0.5">
            {(["any", "all"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setLogic(mode)}
                className={`rounded px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-wider ${
                  logic === mode
                    ? "bg-rt-bg-card-hover text-rt-fg"
                    : "text-rt-fg-tertiary"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setSelectedNiches([])}
            className="text-[12px] text-rt-fg-tertiary underline underline-offset-2 hover:text-rt-fg-secondary"
          >
            Clear
          </button>
        </div>
      )}

      <p className="py-3.5 text-[12.5px] text-rt-fg-tertiary">
        <b className="text-rt-fg">{rows.length}</b> of {creators.length} creators
        {selectedNiches.length > 0 && (
          <>
            {" "}· matching <b className="text-rt-fg">{selectedNiches.length}</b>{" "}
            niche{selectedNiches.length > 1 ? "s" : ""} ({logic.toUpperCase()})
          </>
        )}{" "}
        · <b className="text-rt-fg">{niches.length}</b> niches in the vocabulary
      </p>

      {/* Cards */}
      {rows.length === 0 ? (
        <div className="py-20 text-center text-rt-fg-tertiary">
          <p className="text-[16px] text-rt-fg-secondary">No creators match</p>
          <p className="mt-1 text-[13px]">
            Try removing a niche or switching ANY / ALL.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(268px,1fr))] gap-3">
          {rows.map((creator, index) => {
            const stat = creator.stats?.[window_] ?? null
            const isPicked = picked.has(creator.key)
            return (
              <div
                key={creator.key}
                role="button"
                tabIndex={0}
                onClick={() =>
                  tagMode ? togglePicked(creator.key) : setOpenCreator(creator.key)
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    if (tagMode) togglePicked(creator.key)
                    else setOpenCreator(creator.key)
                  }
                }}
                className={`relative flex cursor-pointer flex-col gap-3 rounded-xl border p-4 text-left transition-all hover:-translate-y-0.5 ${
                  isPicked
                    ? "border-rt-magenta bg-rt-bg-card-hover ring-1 ring-rt-magenta"
                    : "border-white/10 bg-rt-bg-card hover:border-white/20"
                }`}
              >
                {ranked && (
                  <span
                    className={`absolute left-3 top-3 z-10 grid h-6 min-w-6 place-items-center rounded-lg px-1.5 text-[11.5px] font-bold ${
                      index < 3
                        ? "bg-gradient-to-r from-rt-magenta to-rt-purple text-white"
                        : "border border-white/15 bg-rt-bg-elevated text-rt-fg-tertiary"
                    }`}
                  >
                    #{index + 1}
                  </span>
                )}

                {tagMode && (
                  <span
                    className={`absolute right-3 top-3 z-10 grid size-5 place-items-center rounded-md border text-[11px] ${
                      isPicked
                        ? "border-transparent bg-rt-magenta text-white"
                        : "border-white/20 bg-rt-bg-black"
                    }`}
                  >
                    {isPicked && "✓"}
                  </span>
                )}

                <div className={`flex items-center gap-3 ${ranked ? "pl-8" : ""} ${tagMode ? "pr-7" : ""}`}>
                  <div
                    style={avatarStyle(creator.key)}
                    className="grid size-10 shrink-0 place-items-center rounded-full text-[15px] font-semibold text-white"
                  >
                    {initials(creator.key)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-semibold text-rt-fg">
                      @{creator.username}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-rt-fg-tertiary">
                      {creator.scouted ? (
                        <span className="rounded bg-rt-amber/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-rt-amber">
                          Never booked
                        </span>
                      ) : (
                        <span>
                          {stat
                            ? `${stat.posts} posts · ${compact(stat.total)} views`
                            : `no posts in ${LIBRARY_WINDOW_LABELS[window_]}`}
                        </span>
                      )}
                      {creator.slow && (
                        <span className="rounded-full bg-rt-amber/15 px-1.5 py-0.5 text-[10px] font-bold text-rt-amber">
                          Slow
                        </span>
                      )}
                    </p>
                  </div>
                </div>

                {/* Inline tagging — the fast path Jake asked for */}
                <div
                  className="flex min-h-[22px] flex-wrap gap-1.5"
                  onClick={(e) => e.stopPropagation()}
                >
                  {creator.niches.map((name) => (
                    <span
                      key={name}
                      style={nicheStyle(name)}
                      className="inline-flex items-center gap-1 rounded-full py-0.5 pl-2.5 pr-1.5 text-[11px] font-semibold"
                    >
                      {name}
                      <button
                        type="button"
                        aria-label={`Remove ${name}`}
                        onClick={() => tagOne(creator, name)}
                        className="opacity-60 hover:opacity-100"
                      >
                        <X className="size-2.5" />
                      </button>
                    </span>
                  ))}
                  <button
                    type="button"
                    onClick={(e) =>
                      setPicker({
                        anchor: e.currentTarget,
                        mode: "single",
                        username: creator.key,
                      })
                    }
                    className="rounded-full border border-dashed border-white/20 px-2.5 py-0.5 text-[11.5px] font-semibold text-rt-fg-tertiary transition-colors hover:border-rt-magenta hover:text-rt-fg"
                  >
                    + niche
                  </button>
                </div>

                <div className="mt-auto grid grid-cols-3 gap-1 border-t border-white/10 pt-3">
                  <div>
                    <p className="text-[9.5px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                      {creator.rate_source === "override" ? "Set rate" : "Last rate"}
                    </p>
                    <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-rt-fg">
                      {creator.rate === null ? "—" : `$${creator.rate}`}
                      {creator.rate_source === "override" && (
                        <span className="ml-0.5 align-super text-[9px] text-rt-magenta">
                          ●
                        </span>
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-[9.5px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                      Typical {LIBRARY_WINDOW_LABELS[window_]}
                    </p>
                    <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-rt-fg">
                      {stat ? compact(stat.median) : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[9.5px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                      Proj. CPM
                    </p>
                    <p
                      className={`mt-0.5 text-[14px] font-semibold tabular-nums ${cpmTone(stat?.pcpm)}`}
                    >
                      {stat?.pcpm == null ? "—" : `$${stat.pcpm}`}
                    </p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Bulk action bar */}
      {tagMode && (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-2xl border border-white/15 bg-rt-bg-elevated p-3 shadow-2xl">
          <span className="pl-1 text-[13.5px] font-semibold text-rt-fg">
            {picked.size} selected
          </span>
          <span className="h-5 w-px bg-white/10" />
          <Button
            disabled={picked.size === 0}
            onClick={(e) => setPicker({ anchor: e.currentTarget, mode: "bulk" })}
          >
            Apply niche
          </Button>
          <Button
            variant="outline"
            onClick={() => setPicked(new Set(rows.map((r) => r.key)))}
          >
            Select all shown
          </Button>
          <Button variant="outline" onClick={() => setPicked(new Set())}>
            Clear
          </Button>
        </div>
      )}

      {picker && (
        <NichePicker
          anchor={picker.anchor}
          niches={niches}
          mode={picker.mode === "single" ? "single" : "bulk"}
          selected={
            picker.mode === "filter"
              ? selectedNiches
              : picker.mode === "single"
                ? creators.find((c) => c.key === picker.username)?.niches ?? []
                : []
          }
          onToggle={(name) => {
            if (picker.mode === "filter") {
              toggleFilterNiche(name)
            } else if (picker.mode === "single") {
              const creator = creators.find((c) => c.key === picker.username)
              if (creator) tagOne(creator, name)
            } else {
              bulkTag(name)
            }
          }}
          onCreate={(name) => {
            if (picker.mode === "single") {
              const creator = creators.find((c) => c.key === picker.username)
              if (creator) tagOne(creator, name)
            } else if (picker.mode === "bulk") {
              bulkTag(name)
            }
          }}
          onClose={() => setPicker(null)}
        />
      )}

      {activeCreator && (
        <CreatorDrawer
          key={activeCreator.key}
          creator={activeCreator}
          window={window_}
          niches={niches}
          onClose={() => setOpenCreator(null)}
        />
      )}

      {showManager && (
        <NicheManager niches={niches} onClose={() => setShowManager(false)} />
      )}

      {showAdd && (
        <AddCreatorDialog niches={niches} onClose={() => setShowAdd(false)} />
      )}
    </div>
  )
}
