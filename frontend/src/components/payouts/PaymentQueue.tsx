// Ready-for-payment queue on the Payouts page. No money moves here — this is
// the list Jake reviews; batch payouts (step 3) pay from the "Ready" list.
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { METHOD_LABEL, money, payoutAdmin } from "@/lib/payouts"
import type { BookingMarkAction, QueueRow } from "@/lib/payouts"

const REASON: Record<QueueRow["reason"], string> = {
  posts_complete: "All posts in",
  trusted_confirmed: "Trusted · accepted",
  manual: "Marked ready by hand",
  trusted_unconfirmed: "Trusted · waiting on acceptance",
  posts_incomplete: "Posts incomplete",
}

const ISSUE: Record<string, { label: string; cls: string }> = {
  missing: { label: "No payment details", cls: "text-rt-red" },
  changed: { label: "Details changed — review first", cls: "text-rt-red" },
  unconfirmed: { label: "Details not confirmed by creator", cls: "text-rt-amber" },
}

const TRUST_NEXT: Record<QueueRow["trust_override"], QueueRow["trust_override"]> = {
  "": "trusted",
  trusted: "standard",
  standard: "",
}

function TrustBadge({ row, onCycle }: { row: QueueRow; onCycle: () => void }) {
  const label = row.trusted ? "Trusted" : "New"
  const suffix = row.trust_override ? " (manual)" : ` (${row.delivered_campaigns} done)`
  return (
    <button
      type="button"
      title="Click to cycle: automatic → always trusted → always standard"
      onClick={onCycle}
      className={`rounded-full px-2 py-0.5 text-[11px] ${row.trusted ? "bg-rt-purple/20 text-rt-fg" : "bg-white/5 text-rt-fg-tertiary"}`}
    >
      {label}
      {suffix}
    </button>
  )
}

interface RowActionsProps {
  row: QueueRow
  section: "ready" | "awaiting" | "not_ready"
  onMark: (row: QueueRow, action: BookingMarkAction) => void
}

function RowActions({ row, section, onMark }: RowActionsProps) {
  if (section === "awaiting") {
    return (
      <button type="button" className="text-xs text-rt-green hover:underline" onClick={() => onMark(row, "confirm")}>
        Accepted booking ✓
      </button>
    )
  }
  if (section === "not_ready") {
    return (
      <button type="button" className="text-xs text-rt-fg-secondary hover:underline" onClick={() => onMark(row, "ready")}>
        Mark ready anyway
      </button>
    )
  }
  if (row.reason === "trusted_confirmed" || row.reason === "manual") {
    return (
      <button type="button" className="text-xs text-rt-fg-tertiary hover:underline" onClick={() => onMark(row, "clear")}>
        Undo
      </button>
    )
  }
  return null
}

function QueueTable({ rows, section, onMark, onTrust }: {
  rows: QueueRow[]
  section: RowActionsProps["section"]
  onMark: RowActionsProps["onMark"]
  onTrust: (row: QueueRow) => void
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-white/8">
      <table className="w-full text-sm">
        <tbody>
          {rows.map((r) => {
            const issue = ISSUE[r.destination_issue]
            return (
              <tr key={`${r.slug}-${r.username}-${r.platform}`} className="border-t border-white/5 first:border-t-0 align-top">
                <td className="px-4 py-2">
                  <div className="text-rt-fg">@{r.handle}</div>
                  <TrustBadge row={r} onCycle={() => onTrust(r)} />
                </td>
                <td className="px-4 py-2 text-rt-fg-secondary">
                  {r.campaign}
                  <div className="text-xs text-rt-fg-tertiary">
                    {r.platform} · {r.posts_done}/{r.posts_owed} posts · {REASON[r.reason]}
                  </div>
                </td>
                <td className="px-4 py-2 text-xs">
                  {r.destination ? (
                    <span className="text-rt-fg-secondary">
                      {METHOD_LABEL[r.method] ?? r.method} <span className="font-mono">{r.destination}</span>
                    </span>
                  ) : null}
                  {issue && <div className={issue.cls}>{issue.label}</div>}
                </td>
                <td className="px-4 py-2 text-right text-rt-fg whitespace-nowrap">{money(r.amount)}</td>
                <td className="px-4 py-2 text-right whitespace-nowrap">
                  <RowActions row={r} section={section} onMark={onMark} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function PaymentQueue({ adminKey }: { adminKey: string }) {
  const qc = useQueryClient()
  const [showNotReady, setShowNotReady] = useState(false)
  const queue = useQuery({
    queryKey: ["payouts", "queue", adminKey],
    queryFn: () => payoutAdmin.queue(adminKey),
    retry: false,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ["payouts"] })
  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : "Request failed")

  const mark = useMutation({
    mutationFn: ({ row, action }: { row: QueueRow; action: BookingMarkAction }) =>
      payoutAdmin.markBooking(adminKey, row, action),
    onSuccess: refresh,
    onError,
  })
  const trust = useMutation({
    mutationFn: (row: QueueRow) => payoutAdmin.setTrust(adminKey, row.username, TRUST_NEXT[row.trust_override]),
    onSuccess: refresh,
    onError,
  })

  if (queue.isLoading) return <p className="text-sm text-rt-fg-tertiary">Loading payment queue…</p>
  if (queue.error) return <p className="text-sm text-rt-red">{queue.error.message}</p>
  const q = queue.data
  if (!q) return null

  const onMark = (row: QueueRow, action: BookingMarkAction) => mark.mutate({ row, action })
  const onTrust = (row: QueueRow) => trust.mutate(row)

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-rt-fg">Ready for payment</h2>
          <p className="text-xs text-rt-fg-tertiary">
            Active campaigns only. New creators: ready when all posts are in. Trusted ({q.trusted_min_campaigns}+
            delivered campaigns): ready once they accept the booking.
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold text-rt-fg">{money(q.totals.ready_amount)}</div>
          <div className="text-xs text-rt-fg-tertiary">
            {q.totals.ready_count} bookings · {money(q.totals.payable_now)} payable now
          </div>
          <div className="text-xs text-rt-fg-tertiary">
            {Object.entries(q.totals.by_method)
              .map(([m, v]) => `${METHOD_LABEL[m] ?? "No details"} ${money(v)}`)
              .join(" · ")}
          </div>
        </div>
      </div>

      {q.ready.length ? (
        <QueueTable rows={q.ready} section="ready" onMark={onMark} onTrust={onTrust} />
      ) : (
        <p className="text-sm text-rt-fg-tertiary">Nobody is ready for payment right now.</p>
      )}

      {q.awaiting_confirmation.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-rt-fg">
            Trusted creators — confirm they accepted ({q.awaiting_confirmation.length})
          </h3>
          <QueueTable rows={q.awaiting_confirmation} section="awaiting" onMark={onMark} onTrust={onTrust} />
        </div>
      )}

      <div className="space-y-2">
        <button
          type="button"
          onClick={() => setShowNotReady((v) => !v)}
          className="text-sm text-rt-fg-secondary hover:text-rt-fg"
        >
          {showNotReady ? "▾" : "▸"} Posts still coming ({q.not_ready.length})
        </button>
        {showNotReady && <QueueTable rows={q.not_ready} section="not_ready" onMark={onMark} onTrust={onTrust} />}
      </div>
    </section>
  )
}
