import { useQuery } from "@tanstack/react-query"
import { payoutAdmin } from "@/lib/payouts"
import type { PayoutEvent } from "@/lib/payouts"
import { usePayoutSessionIsActive, usePayoutSessionPrefix } from "@/lib/payoutSession"

const EVENT_LABEL: Record<string, string> = {
  created: "Creator added",
  confirmed: "Creator confirmed",
  changed: "Creator CHANGED",
  backfilled: "Backfilled from campaign rows",
  admin_set: "Set in the Hub",
  token_issued: "Link issued",
  token_rotated: "Link replaced",
  flag_cleared: "Change reviewed",
}

function describe(e: PayoutEvent) {
  const to = e.new_destination ? `${e.new_method} ${e.new_destination}` : ""
  const from = e.old_destination ? `${e.old_method} ${e.old_destination}` : ""
  if (e.event === "changed") return `${from} → ${to}`
  return to
}

export function PayoutHistory({ adminKey, username }: { adminKey: string; username: string }) {
  const prefix = usePayoutSessionPrefix()
  const isActive = usePayoutSessionIsActive()
  const q = useQuery({
    queryKey: [...prefix, "events", username],
    queryFn: async ({ signal }) => {
      if (!isActive() || signal.aborted) throw new Error("Payout session closed")
      const result = await payoutAdmin.events(adminKey, username)
      if (!isActive() || signal.aborted) throw new Error("Payout session closed")
      return result
    },
  })
  if (q.isLoading) return <p className="text-xs text-rt-fg-tertiary mt-2">Loading history…</p>
  if (q.error) return <p className="text-xs text-rt-red mt-2">{q.error.message}</p>
  const events = q.data?.events ?? []
  if (!events.length) return <p className="text-xs text-rt-fg-tertiary mt-2">No history yet.</p>
  return (
    <ul className="mt-2 space-y-1">
      {events.map((e) => (
        <li key={e.id} className="text-xs flex gap-2">
          <span className="text-rt-fg-tertiary shrink-0">{new Date(e.created_at).toLocaleString()}</span>
          <span className={e.event === "changed" ? "text-rt-red" : "text-rt-fg-secondary"}>
            {EVENT_LABEL[e.event] ?? e.event}
          </span>
          <span className="font-mono text-rt-fg-secondary break-all">{describe(e)}</span>
        </li>
      ))}
    </ul>
  )
}
