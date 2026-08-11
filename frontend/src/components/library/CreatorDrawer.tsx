import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Loader2, X } from "lucide-react"
import { useSetLibraryNiches, useUpdateLibraryCreator } from "@/lib/queries"
import {
  LIBRARY_WINDOW_LABELS,
  type LibraryCreator,
  type LibraryNiche,
  type LibraryWindow,
} from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NichePicker } from "./NichePicker"
import { avatarStyle, initials, nicheStyle } from "./nicheColors"

interface Props {
  creator: LibraryCreator
  window: LibraryWindow
  niches: LibraryNiche[]
  onClose: () => void
}

function compact(value: number | null | undefined): string {
  if (!value) return "—"
  if (value >= 1_000_000)
    return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`
  return String(value)
}

function cpmTone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-rt-fg-tertiary"
  if (value < 1) return "text-rt-green"
  if (value <= 2) return "text-rt-amber"
  return "text-rt-red"
}

function Kpi({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note?: string
  tone?: string
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-rt-bg-card p-3">
      <p className="text-[9.5px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
        {label}
      </p>
      <p className={`mt-1 text-[19px] font-semibold tabular-nums ${tone ?? "text-rt-fg"}`}>
        {value}
      </p>
      {note && <p className="mt-0.5 text-[11px] text-rt-fg-tertiary">{note}</p>}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center gap-2">
      <span className="text-[10px] font-bold uppercase tracking-[0.09em] text-rt-fg-tertiary">
        {children}
      </span>
      <span className="h-px flex-1 bg-white/10" />
    </div>
  )
}

export function CreatorDrawer({ creator, window: win, niches, onClose }: Props) {
  const [editingRate, setEditingRate] = useState(false)
  const [rateDraft, setRateDraft] = useState(String(creator.rate ?? ""))
  const [note, setNote] = useState(creator.note)
  const [posts, setPosts] = useState("5")
  const [perPost, setPerPost] = useState(String(creator.rate ?? 0))
  const [pickerAnchor, setPickerAnchor] = useState<HTMLElement | null>(null)

  const update = useUpdateLibraryCreator()
  const setNiches = useSetLibraryNiches()

  // When the saved rate changes (this drawer just wrote one), resync the
  // fields derived from it. Adjusting during render is React's documented
  // alternative to a setState-in-effect and avoids the extra paint.
  const [lastRate, setLastRate] = useState(creator.rate)
  if (creator.rate !== lastRate) {
    setLastRate(creator.rate)
    setPerPost(String(creator.rate ?? 0))
    setRateDraft(String(creator.rate ?? ""))
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !pickerAnchor) onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose, pickerAnchor])

  const stat = creator.stats?.[win] ?? null
  const total = (Number(perPost) || 0) * (Number(posts) || 0)

  async function saveRate() {
    const value = parseFloat(rateDraft)
    if (Number.isNaN(value) || value <= 0) {
      toast.error("Enter a rate greater than zero")
      return
    }
    try {
      await update.mutateAsync({ username: creator.key, data: { rate: value } })
      toast.success(`@${creator.username} now books at $${value}/post`)
      setEditingRate(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save that rate")
    }
  }

  async function clearRate() {
    try {
      await update.mutateAsync({ username: creator.key, data: { rate: null } })
      toast.success("Back to the last booked rate")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't clear that rate")
    }
  }

  async function toggleNiche(name: string) {
    const next = creator.niches.includes(name)
      ? creator.niches.filter((n) => n !== name)
      : [...creator.niches, name]
    try {
      await setNiches.mutateAsync({ username: creator.key, niches: next })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save that tag")
    }
  }

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/70"
        onClick={onClose}
        aria-hidden
      />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[468px] flex-col border-l border-white/15 bg-rt-bg-raised">
        <header className="flex items-start gap-3.5 border-b border-white/10 p-5">
          <div
            style={avatarStyle(creator.key)}
            className="grid size-14 shrink-0 place-items-center rounded-full text-[22px] font-semibold text-white"
          >
            {initials(creator.key)}
          </div>
          <div className="min-w-0 pt-1">
            <p className="text-[18px] font-semibold text-rt-fg">
              @{creator.username}
            </p>
            <p className="mt-1 text-[12px] text-rt-fg-tertiary">
              {creator.scouted
                ? "Never booked"
                : `${creator.campaigns} campaigns · ${creator.posts_done} posts`}
              {creator.followers > 0 && ` · ${compact(creator.followers)} followers`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-lg p-1 text-rt-fg-tertiary hover:bg-rt-bg-card hover:text-rt-fg"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto p-5 pb-12">
          <section>
            <SectionTitle>Niches</SectionTitle>
            <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-rt-bg-card p-2.5">
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
                    onClick={() => toggleNiche(name)}
                    className="opacity-60 hover:opacity-100"
                  >
                    <X className="size-2.5" />
                  </button>
                </span>
              ))}
              <button
                type="button"
                onClick={(e) => setPickerAnchor(e.currentTarget)}
                className="rounded-full border border-dashed border-white/20 px-3 py-0.5 text-[11.5px] font-semibold text-rt-fg-tertiary hover:border-rt-magenta hover:text-rt-fg"
              >
                + add niche
              </button>
            </div>
          </section>

          <section>
            <SectionTitle>Rate</SectionTitle>
            <div className="overflow-hidden rounded-xl border border-white/10 bg-rt-bg-card">
              <div className="border-b border-white/10 p-4">
                {editingRate ? (
                  <div className="flex items-center gap-2">
                    <Input
                      autoFocus
                      type="number"
                      step="0.01"
                      value={rateDraft}
                      onChange={(e) => setRateDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveRate()
                        if (e.key === "Escape") setEditingRate(false)
                      }}
                      className="border-rt-magenta text-[17px] font-semibold"
                    />
                    <Button onClick={saveRate} disabled={update.isPending}>
                      {update.isPending ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        "Save"
                      )}
                    </Button>
                    <Button variant="outline" onClick={() => setEditingRate(false)}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <>
                    <div className="flex items-baseline gap-2">
                      <span className="text-[30px] font-semibold tabular-nums tracking-tight text-rt-fg">
                        {creator.rate === null ? "—" : `$${creator.rate}`}
                      </span>
                      <span className="text-[13px] text-rt-fg-tertiary">per post</span>
                      <button
                        type="button"
                        onClick={() => setEditingRate(true)}
                        className="ml-auto rounded-lg bg-rt-bg-elevated px-2.5 py-1 text-[11.5px] font-semibold text-rt-fg-tertiary hover:text-rt-fg"
                      >
                        Edit
                      </button>
                    </div>
                    <p className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-rt-fg-tertiary">
                      {creator.rate_source === "override" ? (
                        <>
                          <span className="rounded bg-gradient-to-r from-rt-magenta to-rt-purple px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wide text-white">
                            Set by you
                          </span>
                          <button
                            type="button"
                            onClick={clearRate}
                            className="underline underline-offset-2 hover:text-rt-fg"
                          >
                            use last booked
                          </button>
                        </>
                      ) : creator.rate_source === "booking" ? (
                        <span>
                          From last booking
                          {creator.last_booked_at && ` · ${creator.last_booked_at}`}
                        </span>
                      ) : (
                        <span>No rate on file</span>
                      )}
                    </p>
                  </>
                )}
              </div>

              <div className="space-y-3 p-4">
                <p className="rounded-lg border border-rt-magenta/20 bg-rt-magenta/5 px-3 py-2 text-[11.5px] text-rt-fg-secondary">
                  This is the rate that auto-fills when you add @{creator.username} to
                  a campaign.
                </p>
                <div className="flex items-end gap-2.5">
                  <label className="flex-1">
                    <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                      $ / post
                    </span>
                    <Input
                      type="number"
                      step="0.01"
                      value={perPost}
                      onChange={(e) => setPerPost(e.target.value)}
                    />
                  </label>
                  <span className="pb-2.5 text-rt-fg-tertiary">×</span>
                  <label className="flex-1">
                    <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                      Posts
                    </span>
                    <Input
                      type="number"
                      min="1"
                      value={posts}
                      onChange={(e) => setPosts(e.target.value)}
                    />
                  </label>
                  <span className="pb-2.5 text-rt-fg-tertiary">=</span>
                  <label className="flex-1">
                    <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                      Total
                    </span>
                    <Input readOnly value={total ? total.toFixed(2) : "0.00"} />
                  </label>
                </div>
              </div>
            </div>
          </section>

          <section>
            <SectionTitle>Value at this rate</SectionTitle>
            <div className="grid grid-cols-2 gap-2">
              <Kpi
                label={`Projected CPM — ${LIBRARY_WINDOW_LABELS[win]}`}
                value={stat?.pcpm == null ? "—" : `$${stat.pcpm}`}
                note="rate ÷ typical views"
                tone={cpmTone(stat?.pcpm)}
              />
              <Kpi
                label="Worst-case CPM"
                value={stat?.floor == null ? "—" : `$${stat.floor}`}
                note="if they land in their bottom quarter"
                tone={cpmTone(stat?.floor)}
              />
              <Kpi
                label="Viral rate"
                value={stat ? `${stat.viral_rate}%` : "—"}
                note="posts over 100k"
              />
              <Kpi
                label={`Posts — ${LIBRARY_WINDOW_LABELS[win]}`}
                value={stat ? String(stat.posts) : "—"}
                note="how much they can absorb"
              />
            </div>
          </section>

          <section>
            <SectionTitle>Reach</SectionTitle>
            <div className="grid grid-cols-2 gap-2">
              <Kpi
                label="Typical — last 30d"
                value={compact(creator.stats?.w30?.median)}
                note={
                  creator.stats?.w30 ? `${creator.stats.w30.posts} posts` : "no recent posts"
                }
              />
              <Kpi
                label="Typical — last 60d"
                value={compact(creator.stats?.w60?.median)}
                note={creator.stats?.w60 ? `${creator.stats.w60.posts} posts` : "—"}
              />
              <Kpi label="Views — last 60d" value={compact(creator.stats?.w60?.total)} />
              <Kpi label="Biggest post" value={compact(stat?.peak)} />
            </div>
            {creator.stats_updated_at && (
              <p className="mt-2 text-[11px] text-rt-fg-tertiary">
                Live from Tides Trackers · updated{" "}
                {creator.stats_updated_at.slice(0, 16).replace("T", " ")}
              </p>
            )}
          </section>

          <section>
            <SectionTitle>Notes</SectionTitle>
            <Button
              variant={creator.slow ? "default" : "outline"}
              onClick={() =>
                update.mutate({
                  username: creator.key,
                  data: { slow: !creator.slow },
                })
              }
            >
              Slow to post
            </Button>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onBlur={() => {
                if (note !== creator.note) {
                  update.mutate({ username: creator.key, data: { note } })
                }
              }}
              placeholder="Anything worth remembering — turnaround time, how much nudging they need, how many posts they can handle at once…"
              className="mt-2 min-h-[62px] w-full resize-y rounded-xl border border-white/10 bg-rt-bg-card p-3 text-[13px] text-rt-fg placeholder:text-rt-fg-tertiary focus:border-white/20 focus:outline-none"
            />
          </section>

          <section>
            <SectionTitle>Payout</SectionTitle>
            <div className="rounded-xl border border-white/10 bg-rt-bg-card p-3">
              <p className="text-[9.5px] font-bold uppercase tracking-wider text-rt-fg-tertiary">
                PayPal
              </p>
              <p className="mt-1 break-all text-[13px] text-rt-fg">
                {creator.paypal_email || (
                  <span className="text-rt-fg-tertiary">Not on file</span>
                )}
              </p>
            </div>
          </section>
        </div>
      </aside>

      {pickerAnchor && (
        <NichePicker
          anchor={pickerAnchor}
          niches={niches}
          selected={creator.niches}
          onToggle={toggleNiche}
          onCreate={toggleNiche}
          onClose={() => setPickerAnchor(null)}
        />
      )}
    </>
  )
}
