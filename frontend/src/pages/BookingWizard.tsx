import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Search, Music, Zap, Check, ArrowRight, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { useSounds, useSoundFit, useNetwork } from "@/lib/queries"
import { api } from "@/lib/api"
import type { TargetSound, SoundFitCreator, NetworkCreator } from "@/lib/types"

/* ============================================================
   BOOKING WIZARD (CAMP-83)
   Fresh sound → best-fit creators → select → book into outreach.
   Turns the shipped sound-fit intelligence into the actual action.
   ============================================================ */

function fmtMoney(v: number): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

export default function BookingWizard() {
  const navigate = useNavigate()
  const { data: soundsData, isLoading: soundsLoading } = useSounds()
  const { data: network } = useNetwork()
  const [soundQuery, setSoundQuery] = useState("")
  const [picked, setPicked] = useState<TargetSound | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [booking, setBooking] = useState(false)
  const { data: fit, isLoading: fitLoading } = useSoundFit(picked?.sound_id ?? null)

  // default rate/posts per creator from the network roster (for the budget tally)
  const rateByCreator = useMemo(() => {
    const m = new Map<string, { rate: number; posts: number }>()
    ;(network ?? []).forEach((c: NetworkCreator) =>
      m.set(c.username.toLowerCase(), { rate: c.default_rate, posts: c.default_posts })
    )
    return m
  }, [network])

  const sounds = useMemo(() => {
    const list = soundsData?.sounds ?? []
    if (!soundQuery.trim()) return list
    const q = soundQuery.toLowerCase()
    return list.filter((s) => s.artist.toLowerCase().includes(q) || s.song.toLowerCase().includes(q))
  }, [soundsData, soundQuery])

  const creators = fit?.creators ?? []
  const maxFit = creators.length ? Math.max(...creators.map((c) => c.fit_score)) : 1

  // Budget tally for the current selection, using network default rate × posts.
  const tally = useMemo(() => {
    let cost = 0
    let posts = 0
    selected.forEach((acct) => {
      const r = rateByCreator.get(acct.replace(/^@/, "").toLowerCase())
      if (r) {
        cost += r.rate * r.posts
        posts += r.posts
      }
    })
    return { cost, posts, count: selected.size }
  }, [selected, rateByCreator])

  function toggle(account: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(account)) next.delete(account)
      else next.add(account)
      return next
    })
  }

  function pickSound(s: TargetSound) {
    setPicked(s)
    setSelected(new Set()) // reset selection when changing sound
  }

  async function book() {
    if (!picked || selected.size === 0) return
    setBooking(true)
    try {
      const payload = Array.from(selected).map((acct) => {
        const key = acct.replace(/^@/, "").toLowerCase()
        const r = rateByCreator.get(key)
        return {
          username: acct.replace(/^@/, ""),
          rate: r?.rate ?? 0,
          posts: r?.posts ?? 1,
        }
      })
      const res = await api.addToOutreach(picked.campaign_slug, payload)
      toast.success(`Added ${res.added ?? payload.length} creator${payload.length !== 1 ? "s" : ""} to ${picked.song} outreach`)
      navigate(`/campaign/${picked.campaign_slug}/outreach`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't book these creators")
    } finally {
      setBooking(false)
    }
  }

  return (
    <div className="relative min-h-screen rt-grain">
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background:
            "radial-gradient(800px 400px at 15% -5%, rgba(225,0,195,0.10), transparent 60%), radial-gradient(700px 500px at 95% 0%, rgba(133,0,215,0.10), transparent 55%)",
        }}
      />
      <div className="relative z-10 mx-auto max-w-[1200px] px-6 py-10">
        <header className="mb-8">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-rt-fg-tertiary">
            <Zap className="h-3 w-3 text-rt-magenta" />
            Booking Wizard
          </div>
          <h1 className="mt-2 font-display text-4xl font-bold leading-none">
            Book a <span className="rt-gradient-text">Fresh Sound</span>
          </h1>
          <p className="mt-2 max-w-xl text-sm text-rt-fg-secondary">
            Pick a sound, see the creators most likely to break it, select your
            roster, and book them into the campaign's outreach in one move.
          </p>
        </header>

        <div className="grid grid-cols-[300px_1fr] gap-6">
          {/* Step 1: sound picker */}
          <div className="rounded-2xl border border-white/8 bg-rt-bg-raised/60 p-3 backdrop-blur">
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-white/8 bg-rt-bg-black px-3 py-2">
              <Search className="h-3.5 w-3.5 text-rt-fg-tertiary" />
              <input
                value={soundQuery}
                onChange={(e) => setSoundQuery(e.target.value)}
                placeholder="Search sounds…"
                className="w-full bg-transparent text-sm text-rt-fg outline-none placeholder:text-rt-fg-tertiary"
              />
            </div>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
              {soundsLoading && (
                <div className="px-2 py-8 text-center text-xs text-rt-fg-tertiary">Loading sounds…</div>
              )}
              {sounds.map((s) => {
                const active = picked?.sound_id === s.sound_id
                return (
                  <button
                    key={s.sound_id}
                    onClick={() => pickSound(s)}
                    className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                      active ? "border border-rt-magenta/30 bg-rt-magenta/12" : "border border-transparent hover:bg-white/[0.03]"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <div className="truncate text-sm font-medium text-rt-fg">{s.song || s.sound_id}</div>
                      {s.freshness === "fresh" && (
                        <span className="shrink-0 rounded border border-rt-green/40 bg-rt-green/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-rt-green">
                          fresh
                        </span>
                      )}
                    </div>
                    <div className="truncate text-xs text-rt-fg-tertiary">{s.artist || "—"}</div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Step 2: ranked creators + book */}
          <div>
            {!picked && (
              <div className="flex h-full min-h-[300px] items-center justify-center rounded-2xl border border-dashed border-white/10 text-sm text-rt-fg-tertiary">
                <div className="text-center">
                  <Music className="mx-auto mb-3 h-6 w-6 text-rt-fg-tertiary" />
                  Pick a sound to start building the booking.
                </div>
              </div>
            )}

            {picked && (
              <>
                <div className="mb-4 flex items-end justify-between gap-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">Booking for</div>
                    <h2 className="font-display text-2xl font-bold text-rt-fg">
                      {picked.song} <span className="text-rt-fg-tertiary">·</span>{" "}
                      <span className="rt-gradient-text">{picked.artist}</span>
                    </h2>
                  </div>
                  {/* live budget tally */}
                  <div className="rounded-xl border border-white/8 bg-rt-bg-card/60 px-4 py-2 text-right">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary">
                      {tally.count} selected · {tally.posts} posts
                    </div>
                    <div className="rt-num text-lg font-bold text-rt-fg">{fmtMoney(tally.cost)}</div>
                  </div>
                </div>

                {fitLoading && (
                  <div className="px-5 py-16 text-center text-sm text-rt-fg-tertiary">Ranking creators…</div>
                )}

                {fit && (
                  <div className="overflow-hidden rounded-2xl border border-white/8 bg-rt-bg-raised/60 backdrop-blur">
                    <div className="grid grid-cols-[2.5rem_1fr_4.5rem_4rem_1fr] gap-3 border-b border-white/8 px-5 py-3 text-[10px] uppercase tracking-[0.16em] text-rt-fg-tertiary">
                      <span></span>
                      <span>Creator</span>
                      <span className="text-right">Fit</span>
                      <span className="text-right">Rate</span>
                      <span>Why</span>
                    </div>
                    {creators.slice(0, 40).map((c) => (
                      <WizardRow
                        key={c.account}
                        c={c}
                        maxFit={maxFit}
                        selected={selected.has(c.account)}
                        rate={rateByCreator.get(c.account.replace(/^@/, "").toLowerCase())}
                        onToggle={() => toggle(c.account)}
                      />
                    ))}
                  </div>
                )}

                {/* Book CTA */}
                <div className="mt-5 flex items-center justify-end gap-3">
                  <span className="text-xs text-rt-fg-tertiary">
                    Books into <span className="text-rt-fg-secondary">{picked.song}</span>'s outreach
                  </span>
                  <button
                    disabled={selected.size === 0 || booking}
                    onClick={book}
                    className={`flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all ${
                      selected.size === 0 || booking
                        ? "cursor-not-allowed bg-white/5 text-rt-fg-tertiary"
                        : "rt-gradient-bg text-white"
                    }`}
                  >
                    {booking ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                    Book {selected.size > 0 ? selected.size : ""} to outreach
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function WizardRow({
  c,
  maxFit,
  selected,
  rate,
  onToggle,
}: {
  c: SoundFitCreator
  maxFit: number
  selected: boolean
  rate?: { rate: number; posts: number }
  onToggle: () => void
}) {
  const heat = Math.max(6, (c.fit_score / maxFit) * 100)
  return (
    <button
      onClick={onToggle}
      className={`grid w-full grid-cols-[2.5rem_1fr_4.5rem_4rem_1fr] items-center gap-3 border-b border-white/5 px-5 py-3 text-left transition-colors ${
        selected ? "bg-rt-magenta/[0.06]" : "hover:bg-white/[0.03]"
      }`}
    >
      <span
        className={`flex h-5 w-5 items-center justify-center rounded border ${
          selected ? "border-rt-magenta bg-rt-magenta text-white" : "border-white/15"
        }`}
      >
        {selected && <Check className="h-3.5 w-3.5" />}
      </span>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-rt-fg">{c.account}</div>
        <div className="mt-1 h-1 w-full max-w-[160px] overflow-hidden rounded-full bg-white/5">
          <div className="h-full rt-heat" style={{ width: `${heat}%` }} />
        </div>
      </div>
      <span className="rt-num text-right text-sm font-semibold text-rt-fg">{c.fit_score.toFixed(0)}</span>
      <span className="rt-num text-right text-sm text-rt-fg-secondary">
        {rate ? fmtMoney(rate.rate) : "—"}
      </span>
      <div className="flex flex-wrap gap-1">
        {c.reasons.length === 0 && <span className="text-[10px] text-rt-fg-tertiary">general breaker</span>}
        {c.reasons.map((reason) => {
          const onSound = reason.includes("on this sound")
          return (
            <span
              key={reason}
              className={`rounded-md border px-2 py-0.5 text-[10px] ${
                onSound
                  ? "border-rt-magenta/40 bg-rt-magenta/10 text-rt-magenta"
                  : "border-rt-purple/40 bg-rt-purple/10 text-rt-purple"
              }`}
            >
              {reason}
            </span>
          )
        })}
      </div>
    </button>
  )
}
