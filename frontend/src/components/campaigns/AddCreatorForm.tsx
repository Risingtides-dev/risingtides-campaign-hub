import { useState, useCallback } from "react"
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

const fmtViews = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${Math.round(n / 1_000)}K` : `${n}`

export function AddCreatorForm({ onAdd, isPending }: AddCreatorFormProps) {
  const [username, setUsername] = useState("")
  const [postsOwed, setPostsOwed] = useState("5")
  const [totalRate, setTotalRate] = useState("100")
  const [paypalEmail, setPaypalEmail] = useState("")
  const [platform, setPlatform] = useState("tiktok")
  const [lookingUpPaypal, setLookingUpPaypal] = useState(false)
  const [verdict, setVerdict] = useState<IntelVerdict | null>(null)
  const [bookAnyway, setBookAnyway] = useState(false)

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

  const lookupPaypal = useCallback(async () => {
    const name = username.replace(/^@/, "").trim()
    if (!name) return
    void lookupIntel(name)
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
  }, [username, paypalEmail, lookupIntel])

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
    setPostsOwed("5")
    setTotalRate("100")
    setPaypalEmail("")
    setPlatform("tiktok")
    setVerdict(null)
    setBookAnyway(false)
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
            onSelect={lookupPaypal}
            onBlur={lookupPaypal}
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
            onChange={(e) => setPostsOwed(e.target.value)}
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
            onChange={(e) => setTotalRate(e.target.value)}
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
