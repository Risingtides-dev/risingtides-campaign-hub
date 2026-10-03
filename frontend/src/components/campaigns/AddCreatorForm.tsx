import { useState, useCallback, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Plus, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import type { LastRate } from "@/lib/types"
import { CreatorAutocomplete } from "@/components/CreatorAutocomplete"

interface AddCreatorFormProps {
  onAdd: (data: {
    username: string
    posts_owed: number
    total_rate: number
    paypal_email: string
    platform: string
  }) => void
  isPending: boolean
}

// Intelligence verdict for the handle being booked. The Booking Wizard already
// ranks by fit — this closes the OTHER door, the manual add that historically
// re-booked known-cold creators 40-50 times with nobody noticing.
//   cold    → tracked history says they don't break sounds; booking needs an
//             explicit "book anyway" tick (soft gate — diversity trials of
//             UNKNOWN creators stay frictionless by design).
//   breaker → proven sound-breaker, book with confidence.
//   trial   → no tracked history; that's what trials are for.
type IntelVerdict = {
  kind: "cold" | "breaker" | "neutral" | "trial"
  posts?: number
  avgViews?: number
  viralRate?: number
  score?: number
}

const COLD_MIN_POSTS = 15
const COLD_MAX_AVG_VIEWS = 15_000
const BREAKER_VIRAL_RATE = 5
const BREAKER_AVG_VIEWS = 50_000

function verdictFor(intel: {
  posts: number
  avg_views: number
  viral_rate: number
  score_balanced: number
}): IntelVerdict {
  const base = {
    posts: intel.posts,
    avgViews: intel.avg_views,
    viralRate: intel.viral_rate,
    score: intel.score_balanced,
  }
  if (
    intel.posts >= COLD_MIN_POSTS &&
    intel.viral_rate === 0 &&
    intel.avg_views < COLD_MAX_AVG_VIEWS
  ) {
    return { kind: "cold", ...base }
  }
  if (intel.viral_rate >= BREAKER_VIRAL_RATE || intel.avg_views >= BREAKER_AVG_VIEWS) {
    return { kind: "breaker", ...base }
  }
  return { kind: "neutral", ...base }
}

const DEFAULT_POSTS_OWED = "5"
const DEFAULT_TOTAL_RATE = "100"

const fmtViews = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${Math.round(n / 1_000)}K` : `${n}`

export function AddCreatorForm({ onAdd, isPending }: AddCreatorFormProps) {
  const [username, setUsername] = useState("")
  const [postsOwed, setPostsOwed] = useState(DEFAULT_POSTS_OWED)
  const [totalRate, setTotalRate] = useState(DEFAULT_TOTAL_RATE)
  const [paypalEmail, setPaypalEmail] = useState("")
  const [platform, setPlatform] = useState("tiktok")
  const [lookingUpPaypal, setLookingUpPaypal] = useState(false)
  const [verdict, setVerdict] = useState<IntelVerdict | null>(null)
  const [bookAnyway, setBookAnyway] = useState(false)
  const [lastRate, setLastRate] = useState<LastRate | null>(null)
  // Once the price or post count is typed by hand, a lookup must never clobber it.
  const rateTouchedRef = useRef(false)
  // Guards against a slow lookup for a previous handle landing after a newer one.
  const latestLookupRef = useRef("")

  const lookupIntel = useCallback(async (name: string) => {
    setVerdict(null)
    setBookAnyway(false)
    try {
      const intel = await api.getCreatorIntel(name)
      setVerdict(verdictFor(intel))
    } catch {
      // 404 = no tracked posts = a genuinely new creator. Trials are the
      // lifeblood of roster diversity - zero friction, say so positively.
      setVerdict({ kind: "trial" })
    }
  }, [])

  const lookupLastRate = useCallback(async (name: string) => {
    let last: LastRate | null = null
    try {
      last = (await api.getLastRate(name)).last_rate
    } catch {
      // Silently fail - rate lookup is optional, the defaults still work
    }
    if (latestLookupRef.current !== name) return
    setLastRate(last)
    if (rateTouchedRef.current) return
    setTotalRate(last ? String(last.total_rate) : DEFAULT_TOTAL_RATE)
    setPostsOwed(last && last.posts_owed > 0 ? String(last.posts_owed) : DEFAULT_POSTS_OWED)
  }, [])

  // onSelect passes the picked handle; onBlur relies on the typed value.
  const lookupCreator = useCallback(async (selected?: string) => {
    const name = (selected ?? username).replace(/^@/, "").trim()
    if (!name || name === latestLookupRef.current) return
    latestLookupRef.current = name
    void lookupIntel(name)
    void lookupLastRate(name)
    if (paypalEmail.trim()) return

    setLookingUpPaypal(true)
    try {
      const data = await api.getPaypal(name)
      if (data.paypal && !paypalEmail.trim()) {
        setPaypalEmail(data.paypal)
      }
    } catch {
      // Silently fail - paypal lookup is optional
    } finally {
      setLookingUpPaypal(false)
    }
  }, [username, paypalEmail, lookupIntel, lookupLastRate])

  const coldBlocked = verdict?.kind === "cold" && !bookAnyway

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const cleanUsername = username.replace(/^@/, "").trim()
    if (!cleanUsername || coldBlocked) return

    onAdd({
      username: cleanUsername,
      posts_owed: parseInt(postsOwed, 10),
      total_rate: parseFloat(totalRate),
      paypal_email: paypalEmail,
      platform,
    })

    // Reset form
    setUsername("")
    setPostsOwed(DEFAULT_POSTS_OWED)
    setTotalRate(DEFAULT_TOTAL_RATE)
    setPaypalEmail("")
    setPlatform("tiktok")
    setVerdict(null)
    setBookAnyway(false)
    setLastRate(null)
    rateTouchedRef.current = false
    latestLookupRef.current = ""
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5">
      <h3 className="text-[15px] font-semibold mb-3">Add Creator</h3>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2.5">
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Username</label>
          <CreatorAutocomplete
            value={username}
            onChange={setUsername}
            onSelect={lookupCreator}
            onBlur={() => void lookupCreator()}
            className="w-full sm:w-[160px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Platform</label>
          <Select value={platform} onValueChange={setPlatform}>
            <SelectTrigger className="w-full sm:w-[120px] h-9 text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="tiktok">TikTok</SelectItem>
              <SelectItem value="instagram">Instagram</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Posts Owed</label>
          <Input
            type="number"
            min="1"
            value={postsOwed}
            onChange={(e) => {
              rateTouchedRef.current = true
              setPostsOwed(e.target.value)
            }}
            required
            className="w-full sm:w-[90px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Price ($)</label>
          <Input
            type="number"
            step="0.01"
            value={totalRate}
            onChange={(e) => {
              rateTouchedRef.current = true
              setTotalRate(e.target.value)
            }}
            required
            className="w-full sm:w-[110px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">
            PayPal
            {lookingUpPaypal && (
              <Loader2 className="inline size-3 ml-1 animate-spin text-rt-fg-tertiary" />
            )}
          </label>
          <Input
            type="email"
            value={paypalEmail}
            onChange={(e) => setPaypalEmail(e.target.value)}
            placeholder="email@example.com"
            className="w-full sm:w-[200px]"
          />
        </div>
        <Button
          type="submit"
          disabled={isPending || coldBlocked}
          className="bg-rt-magenta hover:bg-rt-purple text-white"
        >
          {isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Plus className="size-3.5" />
          )}
          {isPending ? "Adding..." : "Add"}
        </Button>
        {lastRate && (
          <div className="w-full text-[12px] leading-5 text-rt-fg-tertiary">
            Last booked ${lastRate.total_rate.toLocaleString()} for {lastRate.posts_owed}{" "}
            {lastRate.posts_owed === 1 ? "post" : "posts"}
            {lastRate.campaign && <> · {lastRate.campaign}</>}
            {lastRate.added_date && <> ({lastRate.added_date})</>}
          </div>
        )}
        {verdict && (
          <div className="w-full text-[12px] leading-5">
            {verdict.kind === "cold" && (
              <div className="rounded-[8px] border border-red-500/40 bg-red-500/10 px-3 py-2 text-red-300">
                <span className="font-semibold">Cold history:</span>{" "}
                {verdict.posts} tracked posts · avg {fmtViews(verdict.avgViews ?? 0)} views ·{" "}
                {verdict.viralRate}% viral. This creator has never broken a sound.
                <label className="mt-1 flex items-center gap-2 text-red-200">
                  <input
                    type="checkbox"
                    checked={bookAnyway}
                    onChange={(e) => setBookAnyway(e.target.checked)}
                  />
                  Book anyway (deliberate choice, not autopilot)
                </label>
              </div>
            )}
            {verdict.kind === "breaker" && (
              <span className="text-emerald-300">
                Proven breaker · avg {fmtViews(verdict.avgViews ?? 0)} views ·{" "}
                {verdict.viralRate}% viral · score {verdict.score?.toFixed(0)}
              </span>
            )}
            {verdict.kind === "neutral" && (
              <span className="text-rt-fg-tertiary">
                {verdict.posts} tracked posts · avg {fmtViews(verdict.avgViews ?? 0)} views ·{" "}
                {verdict.viralRate}% viral
              </span>
            )}
            {verdict.kind === "trial" && (
              <span className="text-rt-fg-tertiary">
                No tracked history — new-creator trial. That&apos;s the bench working.
              </span>
            )}
          </div>
        )}
      </form>
    </div>
  )
}
