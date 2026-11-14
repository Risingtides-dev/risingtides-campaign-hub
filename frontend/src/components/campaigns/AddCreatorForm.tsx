import { useState, useRef } from "react"
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
import type { LastRate, LibraryPlatform } from "@/lib/types"
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

// TikTok history informs the existing optional cold-history booking override.
type IntelVerdict = {
  kind: "cold" | "breaker" | "neutral" | "trial" | "unavailable"
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

const normalizeHandle = (value: string) => value.trim().replace(/^@+/, "").replace(/\/+$/, "").toLowerCase()

type LookupIdentity = { name: string; platform: LibraryPlatform }

const DEFAULT_POSTS_OWED = "5"
const DEFAULT_TOTAL_RATE = "100"

const fmtViews = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${Math.round(n / 1_000)}K` : `${n}`

export function AddCreatorForm({ onAdd, isPending }: AddCreatorFormProps) {
  const [username, setUsername] = useState("")
  const [postsOwed, setPostsOwed] = useState(DEFAULT_POSTS_OWED)
  const [totalRate, setTotalRate] = useState(DEFAULT_TOTAL_RATE)
  const [paypalEmail, setPaypalEmail] = useState("")
  const [platform, setPlatform] = useState<LibraryPlatform>("tiktok")
  const [lookingUpPaypal, setLookingUpPaypal] = useState(false)
  const [verdict, setVerdict] = useState<IntelVerdict | null>(null)
  const [bookAnyway, setBookAnyway] = useState(false)
  const [lastRate, setLastRate] = useState<LastRate | null>(null)
  const [rateUnavailable, setRateUnavailable] = useState(false)
  // Identity objects are request generations: editing away and back still
  // invalidates responses from the earlier attempt at the same handle.
  const identityRef = useRef<LookupIdentity>({ name: "", platform: "tiktok" })
  const latestLookupRef = useRef<LookupIdentity | null>(null)
  const rateTouchedRef = useRef(false)
  const paypalTouchedRef = useRef(false)
  const paypalValueRef = useRef("")

  function changeIdentity(name: string, nextPlatform: LibraryPlatform) {
    const normalized = normalizeHandle(name)
    if (identityRef.current.name === normalized && identityRef.current.platform === nextPlatform) return
    identityRef.current = { name: normalized, platform: nextPlatform }
    latestLookupRef.current = null
    setVerdict(null)
    setBookAnyway(false)
    setLastRate(null)
    setRateUnavailable(false)
    setLookingUpPaypal(false)
    if (!rateTouchedRef.current) {
      setTotalRate(DEFAULT_TOTAL_RATE)
      setPostsOwed(DEFAULT_POSTS_OWED)
    }
    if (!paypalTouchedRef.current) {
      paypalValueRef.current = ""
      setPaypalEmail("")
    }
  }

  function changeUsername(value: string) {
    setUsername(value)
    changeIdentity(value, identityRef.current.platform)
  }

  async function lookupIntel(identity: LookupIdentity) {
    if (identity.platform !== "tiktok") return
    try {
      const intel = await api.getCreatorIntel(identity.name)
      if (identityRef.current === identity) setVerdict(verdictFor(intel))
    } catch (error) {
      if (identityRef.current !== identity) return
      const notFound = typeof error === "object" && error !== null && "status" in error && error.status === 404
      setVerdict({ kind: notFound ? "trial" : "unavailable" })
    }
  }

  async function lookupLastRate(identity: LookupIdentity) {
    try {
      const last = (await api.getLastRate(identity.name, identity.platform)).last_rate
      if (identityRef.current !== identity) return
      // An older server or mismatched response cannot prove platform ownership.
      if (last && last.platform?.trim().toLowerCase() !== identity.platform) {
        setRateUnavailable(true)
        return
      }
      setLastRate(last)
      if (rateTouchedRef.current) return
      setTotalRate(last ? String(last.total_rate) : DEFAULT_TOTAL_RATE)
      setPostsOwed(last && last.posts_owed > 0 ? String(last.posts_owed) : DEFAULT_POSTS_OWED)
    } catch {
      if (identityRef.current === identity) setRateUnavailable(true)
    }
  }

  async function lookupPaypal(identity: LookupIdentity) {
    if (paypalTouchedRef.current || paypalValueRef.current.trim()) return
    setLookingUpPaypal(true)
    try {
      const data = await api.getPaypal(identity.name)
      if (identityRef.current === identity && !paypalTouchedRef.current && !paypalValueRef.current.trim() && data.paypal) {
        paypalValueRef.current = data.paypal
        setPaypalEmail(data.paypal)
      }
    } catch {
      // Optional contact lookup does not block a manual booking.
    } finally {
      if (identityRef.current === identity) setLookingUpPaypal(false)
    }
  }

  // Autocomplete selection and its delayed blur may both fire; only one
  // lookup generation runs for the current normalized handle and platform.
  function lookupCreator(selected?: string) {
    if (selected !== undefined) changeUsername(selected)
    const identity = identityRef.current
    if (!identity.name || latestLookupRef.current === identity) return
    latestLookupRef.current = identity
    void lookupIntel(identity)
    void lookupLastRate(identity)
    void lookupPaypal(identity)
  }

  function changePlatform(value: string) {
    if (value !== "tiktok" && value !== "instagram") return
    setPlatform(value)
    changeIdentity(identityRef.current.name, value)
    lookupCreator()
  }

  const coldBlocked = verdict?.kind === "cold" && !bookAnyway

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const cleanUsername = identityRef.current.name
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
    latestLookupRef.current = null
    identityRef.current = { name: "", platform: "tiktok" }
    paypalTouchedRef.current = false
    paypalValueRef.current = ""
    setRateUnavailable(false)
    setLookingUpPaypal(false)
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5">
      <h3 className="text-[15px] font-semibold mb-3">Add Creator</h3>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2.5">
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Username</label>
          <CreatorAutocomplete
            value={username}
            onChange={changeUsername}
            onSelect={lookupCreator}
            onBlur={() => void lookupCreator()}
            className="w-full sm:w-[160px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Platform</label>
          <Select value={platform} onValueChange={changePlatform}>
            <SelectTrigger aria-label="Platform" className="w-full sm:w-[120px] h-9 text-[13px]">
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
            aria-label="Posts Owed"
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
            aria-label="Price ($)"
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
            aria-label="PayPal"
            value={paypalEmail}
            onChange={(e) => {
              paypalTouchedRef.current = true
              paypalValueRef.current = e.target.value
              setPaypalEmail(e.target.value)
            }}
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
        {rateUnavailable && (
          <div role="status" className="w-full text-[12px] text-rt-fg-tertiary">Rate history unavailable.</div>
        )}
        {verdict && (
          <div className="w-full text-[12px] leading-5">
            {verdict.kind === "cold" && (
              <div className="rounded-[8px] border border-red-500/40 bg-red-500/10 px-3 py-2 text-red-300">
                <span className="font-semibold">Cold history:</span>{" "}
                {verdict.posts} tracked posts · avg {fmtViews(verdict.avgViews ?? 0)} views ·{" "}
                {verdict.viralRate}% viral.
                <label className="mt-1 flex items-center gap-2 text-red-200">
                  <input
                    type="checkbox"
                    checked={bookAnyway}
                    onChange={(e) => setBookAnyway(e.target.checked)}
                  />
                  Book anyway
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
            {verdict.kind === "unavailable" && (
              <span role="status" className="text-rt-fg-tertiary">Creator analysis unavailable.</span>
            )}
            {verdict.kind === "trial" && (
              <span className="text-rt-fg-tertiary">
                No tracked TikTok history.
              </span>
            )}
          </div>
        )}
      </form>
    </div>
  )
}
