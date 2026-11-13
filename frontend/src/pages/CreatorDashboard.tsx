// Public creator dashboard: /creator#<token> (also /payout#<token>).
// Rendered OUTSIDE the Hub layout — a creator sees only their own bookings,
// briefs, sounds, payment details and payment history.
import { useEffect, useState } from "react"
import { money, payoutPublic, readTokenFromHash } from "@/lib/payouts"
import type { CreatorDashboardData } from "@/lib/payouts"
import { BookingCard } from "@/components/creator/BookingCard"
import { PayoutDetailsCard } from "@/components/creator/PayoutDetailsCard"

type Phase = "loading" | "invalid" | "ready"

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-rt-bg-black px-4 py-8">
      <div className="mx-auto w-full max-w-xl space-y-5">
        <div className="text-sm font-bold font-display rt-gradient-text">Rising Tides</div>
        {children}
      </div>
    </div>
  )
}

export default function CreatorDashboard() {
  const [token] = useState(readTokenFromHash)
  const [phase, setPhase] = useState<Phase>(token ? "loading" : "invalid")
  const [data, setData] = useState<CreatorDashboardData | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    document.title = "Rising Tides"
  }, [])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    payoutPublic
      .dashboard(token)
      .then((d) => {
        if (cancelled) return
        setData(d)
        setPhase("ready")
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
        setPhase("invalid")
      })
    return () => {
      cancelled = true
    }
  }, [token])

  if (phase === "loading") {
    return (
      <Shell>
        <p className="text-rt-fg-secondary text-sm">Loading…</p>
      </Shell>
    )
  }
  if (phase === "invalid" || !data) {
    return (
      <Shell>
        <p className="text-rt-fg text-sm" role="alert">
          {error || "This link isn't valid anymore. Message us and we'll send you a fresh one."}
        </p>
      </Shell>
    )
  }

  const needsDetails = !data.creator.destination_masked
  return (
    <Shell>
      <header>
        <h1 className="text-2xl font-semibold text-rt-fg">Hey @{data.creator.handle} 👋</h1>
        <p className="text-sm text-rt-fg-secondary mt-1">
          Your campaigns, sounds and payments in one place. You get paid once all your posts are up — usually within
          1–2 business days.
        </p>
      </header>

      {needsDetails && (
        <p className="rounded-lg border border-rt-amber/40 bg-rt-amber/5 px-4 py-3 text-sm text-rt-amber">
          Add your payment details below so we can pay you as soon as your posts are verified.
        </p>
      )}

      <section className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-rt-fg-tertiary">Your campaigns</h2>
        {data.current.length === 0 ? (
          <p className="text-sm text-rt-fg-secondary">No active campaigns right now.</p>
        ) : (
          data.current.map((card) => <BookingCard key={card.campaign} card={card} />)
        )}
      </section>

      <PayoutDetailsCard
        token={token}
        view={data.creator}
        onSaved={(view) => setData((d) => (d ? { ...d, creator: view } : d))}
      />

      <section className="rounded-xl bg-rt-bg-card border border-white/8 p-5">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-rt-fg-tertiary">Payment history</h2>
          <span className="text-sm text-rt-fg">{money(data.totals.paid)} paid</span>
        </div>
        {data.payments.length === 0 ? (
          <p className="text-sm text-rt-fg-secondary">No payments yet.</p>
        ) : (
          <ul className="divide-y divide-white/5">
            {data.payments.map((p, i) => (
              <li key={`${p.campaign}-${p.platform}-${i}`} className="flex justify-between py-2 text-sm">
                <span className="text-rt-fg">
                  {p.campaign}
                  <span className="block text-xs text-rt-fg-tertiary">{p.date || "Date not recorded"}</span>
                </span>
                <span className="text-rt-green">{money(p.amount)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-xs text-rt-fg-tertiary text-center">Only you can see this page. Don't share this link.</p>
    </Shell>
  )
}
