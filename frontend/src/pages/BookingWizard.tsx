import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Search, Music, Check, ArrowRight, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { keys, useSounds, useSoundFit, useNetwork, useLibrary } from "@/lib/queries"
import { api } from "@/lib/api"
import { campaignRoundLabels } from "@/lib/soundLabels"
import type { TargetSound, SoundFitCreator } from "@/lib/types"

/* ============================================================
   BOOKING WIZARD (CAMP-83)
   Fresh sound → best-fit creators → select → book into outreach.
   Turns the shipped sound-fit intelligence into the actual action.
   ============================================================ */

function fmtMoney(v: number): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

export default function BookingWizard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: soundsData, isLoading: soundsLoading, isError: soundsError, refetch: reloadSounds } = useSounds()
  const { data: network, isLoading: networkLoading, isError: networkError, refetch: reloadNetwork } = useNetwork()
  const { data: library, isLoading: libraryLoading, isError: libraryError, refetch: reloadLibrary } = useLibrary("w60", "tiktok")
  const [soundQuery, setSoundQuery] = useState("")
  const [picked, setPicked] = useState<TargetSound | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [booking, setBooking] = useState(false)
  const { data: fit, isLoading: fitLoading, isError: fitError, refetch: reloadFit } = useSoundFit(
    picked?.sound_id ?? null, picked?.campaign_slug, 1000,
  )
  const ratesLoading = libraryLoading || networkLoading
  const ratesError = libraryError || networkError
  const fitMatches = fit?.sound_id === picked?.sound_id && fit?.campaign_slug === picked?.campaign_slug
  const canSelect = !booking && !ratesLoading && !ratesError && !fitLoading && !fitError && fitMatches

  const rateByCreator = useMemo(() => {
    const rates = new Map<string, { perPostRate: number; totalRate: number; posts: number }>()
    const networkByCreator = new Map(
      (network ?? []).filter((c) => !c.platform || c.platform.toLowerCase() === "tiktok")
        .map((c) => [handle(c.username), c]),
    )
    const libraryByCreator = new Map(
      (library?.creators ?? []).map((c) => [handle(c.key || c.username), c]),
    )
    for (const username of new Set([...libraryByCreator.keys(), ...networkByCreator.keys()])) {
      if (!username) continue
      const creator = libraryByCreator.get(username)
      const member = networkByCreator.get(username)
      // Library resolves operator overrides against the latest booking.
      // A recorded invalid/zero rate must not revive an older network rate.
      const libraryHasRate = !!creator && (creator.rate_source !== "none" || creator.rate !== null)
      const posts = member ? member.default_posts : 1
      if (creator?.platform && creator.platform.toLowerCase() !== "tiktok") continue
      if (!Number.isSafeInteger(posts) || posts <= 0) continue
      // Library prices are per post; network defaults and outreach quotes
      // are the total for all promised posts (confirm_outreach stores total_rate).
      const totalRate = libraryHasRate
        ? (typeof creator.rate === "number" ? creator.rate * posts : null)
        : member?.default_rate
      if (typeof totalRate !== "number" || !Number.isFinite(totalRate) || totalRate <= 0) continue
      rates.set(username, { perPostRate: totalRate / posts, totalRate, posts })
    }
    return rates
  }, [library, network])

  const roundLabels = useMemo(() => campaignRoundLabels(soundsData?.sounds ?? []), [soundsData])

  const sounds = useMemo(() => {
    const list = soundsData?.sounds ?? []
    if (!soundQuery.trim()) return list
    const q = soundQuery.trim().toLowerCase()
    return list.filter((s) => s.artist.toLowerCase().includes(q) || s.song.toLowerCase().includes(q))
  }, [soundsData, soundQuery])

  // Rank available paid creators first before limiting the display, rather
  // than filling all 40 slots with unbookable global recommendations.
  const creators = useMemo(() => {
    if (!fitMatches) return []
    const seen = new Set<string>()
    return (fit?.creators ?? []).filter((c) => {
      const key = handle(c.account)
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    }).sort((a, b) => {
      // A selected creator whose rate disappears must stay reachable to remove.
      const group = (c: SoundFitCreator) => !rateByCreator.has(handle(c.account))
        ? (selected.has(handle(c.account)) ? 2 : 0) : 1
      return group(b) - group(a)
    })
  }, [fit, fitMatches, rateByCreator, selected])
  const maxFit = Math.max(1, ...creators.map((c) => c.fit_score))

  const tally = useMemo(() => {
    let cost = 0
    let posts = 0
    let count = 0
    creators.forEach((c) => {
      const key = handle(c.account)
      const rate = rateByCreator.get(key)
      if (selected.has(key) && rate) {
        cost += rate.totalRate
        posts += rate.posts
        count += 1
      }
    })
    return { cost, posts, count }
  }, [creators, selected, rateByCreator])

  function toggle(account: string) {
    if (booking || (!selected.has(handle(account)) && (!canSelect || !rateByCreator.has(handle(account))))) return
    setSelected((prev) => {
      const next = new Set(prev)
      const key = handle(account)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function pickSound(s: TargetSound) {
    setPicked(s)
    setSelected(new Set()) // reset selection when changing sound
  }

  async function book() {
    if (!picked || !canSelect || tally.count === 0) return
    const campaign = picked
    const payload = creators.filter((c) => selected.has(handle(c.account))).map((c) => {
      const username = handle(c.account)
      const rate = rateByCreator.get(username)
      return rate ? { username, rate: rate.totalRate, posts: rate.posts } : null
    }).filter((c): c is { username: string; rate: number; posts: number } => c !== null)
    if (payload.length !== selected.size) {
      setSelected(new Set(payload.map((c) => c.username)))
      toast.error("Creator rates changed. Check your selection before booking.")
      return
    }
    setBooking(true)
    try {
      const res = await api.addToOutreach(campaign.campaign_slug, payload)
      if (res.ok !== true || !Number.isInteger(res.added) || res.added < 0 || res.added > payload.length) {
        toast.error("Booking result couldn't be confirmed. Check campaign outreach before trying again.")
        return
      }
      await queryClient.invalidateQueries({ queryKey: keys.outreach(campaign.campaign_slug) })
      if (res.added === 0) toast.info("Selected creators are already in outreach.")
      else toast.success(`Added ${res.added} creator${res.added !== 1 ? "s" : ""} to ${campaign.song} outreach`)
      navigate(`/campaign/${campaign.campaign_slug}/outreach`)
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
        <header className="mb-6">
          <h1 className="font-display text-2xl font-bold">Booking Wizard</h1>
        </header>

        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          {/* Step 1: sound picker */}
          <div className="rounded-2xl border border-white/8 bg-rt-bg-raised/60 p-3 backdrop-blur">
            <div className="mb-2 flex items-center gap-2 rounded-lg border border-white/8 bg-rt-bg-black px-3 py-2">
              <Search className="h-3.5 w-3.5 text-rt-fg-tertiary" />
              <input
                value={soundQuery}
                onChange={(e) => setSoundQuery(e.target.value)}
                aria-label="Search sounds"
                placeholder="Search sounds…"
                className="w-full bg-transparent text-sm text-rt-fg outline-none placeholder:text-rt-fg-tertiary"
              />
            </div>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
              {soundsLoading && (
                <div className="px-2 py-8 text-center text-xs text-rt-fg-tertiary">Loading sounds…</div>
              )}
              {soundsError && <LoadError message="Couldn't load sounds." onRetry={() => void reloadSounds()} />}
              {!soundsLoading && !soundsError && sounds.length === 0 && (
                <p className="px-2 py-8 text-center text-xs text-rt-fg-tertiary">
                  {soundQuery.trim() ? "No sounds match your search." : "No campaign sounds available."}
                </p>
              )}
              {!soundsError && sounds.map((s) => {
                const active = picked?.campaign_slug === s.campaign_slug
                return (
                  <button
                    key={`${s.campaign_slug}:${s.sound_id}`}
                    disabled={booking}
                    aria-pressed={active}
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
                    {roundLabels.has(s.campaign_slug) && (
                      <div className="mt-1 text-xs text-rt-fg-secondary">{roundLabels.get(s.campaign_slug)}</div>
                    )}
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
                  <div className="min-w-0">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">Booking for</div>
                    <h2 className="break-words font-display text-xl font-bold text-rt-fg sm:text-2xl">
                      {picked.song} <span className="text-rt-fg-tertiary">·</span>{" "}
                      <span className="rt-gradient-text">{picked.artist}</span>
                    </h2>
                    {roundLabels.has(picked.campaign_slug) && (
                      <p className="mt-1 text-xs text-rt-fg-secondary">{roundLabels.get(picked.campaign_slug)}</p>
                    )}
                  </div>
                  {/* live budget tally */}
                  <div className="shrink-0 rounded-xl border border-white/8 bg-rt-bg-card/60 px-3 py-2 text-right">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary">
                      {tally.count} selected · {tally.posts} posts
                    </div>
                    <div className="rt-num text-lg font-bold text-rt-fg">{fmtMoney(tally.cost)}</div>
                  </div>
                </div>

                {(fitLoading || ratesLoading) && (
                  <div role="status" className="px-5 py-16 text-center text-sm text-rt-fg-tertiary">Loading creators…</div>
                )}
                {fitError && <LoadError message="Couldn't rank creators for this sound." onRetry={() => void reloadFit()} />}
                {ratesError && <LoadError message="Couldn't load creator rates." onRetry={() => { void reloadLibrary(); void reloadNetwork() }} />}
                {!fitLoading && !ratesLoading && !fitError && !ratesError && fitMatches && creators.length === 0 && (
                  <p className="py-12 text-center text-sm text-rt-fg-tertiary">No tracked creators qualify for this sound.</p>
                )}
                {!fitLoading && !ratesLoading && !fitError && !ratesError && fitMatches && creators.length > 0 && !creators.some((c) => rateByCreator.has(handle(c.account))) && (
                  <p className="mb-3 text-sm text-rt-fg-secondary">No creator rates available. Set a rate in the <a className="underline" href="/library">Creator Library</a>.</p>
                )}

                {!fitLoading && !ratesLoading && !fitError && !ratesError && fitMatches && creators.length > 0 && (
                  <div className="overflow-hidden rounded-2xl border border-white/8 bg-rt-bg-raised/60 backdrop-blur">
                    <div className="grid grid-cols-[1.25rem_minmax(0,1fr)_3rem_3rem] gap-2 border-b border-white/8 px-3 py-3 sm:grid-cols-[2rem_minmax(0,1fr)_4.5rem_4rem_minmax(0,1fr)] sm:gap-3 sm:px-5 text-[10px] uppercase tracking-[0.16em] text-rt-fg-tertiary">
                      <span></span>
                      <span>Creator</span>
                      <span className="text-right">Fit</span>
                      <span className="text-right">Per post</span>
                      <span className="hidden sm:block">Why</span>
                    </div>
                    {creators.slice(0, 40).map((c) => (
                      <WizardRow
                        key={c.account}
                        c={c}
                        maxFit={maxFit}
                        selected={selected.has(handle(c.account))}
                        disabled={booking || (!canSelect && !selected.has(handle(c.account)))}
                        rate={rateByCreator.get(handle(c.account))}
                        onToggle={() => toggle(c.account)}
                      />
                    ))}
                  </div>
                )}

                {/* Book CTA */}
                <div className="mt-5 flex items-center justify-end gap-3">
                  <button
                    disabled={tally.count === 0 || !canSelect}
                    onClick={book}
                    className={`flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all ${
                      tally.count === 0 || !canSelect
                        ? "cursor-not-allowed bg-white/5 text-rt-fg-tertiary"
                        : "rt-gradient-bg text-white"
                    }`}
                  >
                    {booking ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                    Book {tally.count > 0 ? tally.count : ""} to outreach
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
  disabled,
}: {
  c: SoundFitCreator
  maxFit: number
  selected: boolean
  rate?: { perPostRate: number; totalRate: number; posts: number }
  onToggle: () => void
  disabled: boolean
}) {
  const heat = Math.max(6, (c.fit_score / maxFit) * 100)
  const bookable = (!!rate || selected) && !disabled
  return (
    <button
      onClick={bookable ? onToggle : undefined}
      disabled={!bookable}
      aria-pressed={selected}
      title={rate ? undefined : "Set a paid rate in the Creator Library before booking"}
      className={`grid w-full grid-cols-[1.25rem_minmax(0,1fr)_3rem_3rem] items-center gap-2 border-b border-white/5 px-3 py-3 sm:grid-cols-[2rem_minmax(0,1fr)_4.5rem_4rem_minmax(0,1fr)] sm:gap-3 sm:px-5 text-left transition-colors ${
        !bookable
          ? "cursor-not-allowed opacity-50"
          : selected ? "bg-rt-magenta/[0.06]" : "hover:bg-white/[0.03]"
      }`}
    >
      <span
        className={`flex h-5 w-5 items-center justify-center rounded border ${
          !bookable ? "border-white/10" : selected ? "border-rt-magenta bg-rt-magenta text-white" : "border-white/15"
        }`}
      >
        {selected && bookable && <Check className="h-3.5 w-3.5" />}
      </span>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-rt-fg">{c.account}</div>
        <div className="mt-1 h-1 w-full max-w-[160px] overflow-hidden rounded-full bg-white/5">
          <div className="h-full rt-heat" style={{ width: `${heat}%` }} />
        </div>
      </div>
      <span className="rt-num text-right text-sm font-semibold text-rt-fg">{c.fit_score.toFixed(0)}</span>
      <span className="rt-num text-right text-sm text-rt-fg-secondary">
        {rate ? fmtMoney(rate.perPostRate) : <span className="text-[10px] text-rt-amber">no rate</span>}
      </span>
      <div className="hidden flex-wrap gap-1 sm:flex">
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

function handle(value: string): string {
  return value.trim().replace(/^@+/, "").replace(/\/+$/, "").toLowerCase()
}

function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="px-2 py-4 text-sm text-rt-fg-secondary">
      {message} <button type="button" className="underline" onClick={onRetry}>Retry</button>
    </div>
  )
}
