// Payouts grouped by campaign, mirroring the campaign page: one card per
// active campaign, one row per creator, with plain-English status and two
// clear actions — Confirm (they accepted) and Pay (add to today's payments).
import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { money, payoutAdmin } from "@/lib/payouts"
import type { QueueRow } from "@/lib/payouts"
import { DestinationCell } from "./DestinationCell"
import { RowMenu } from "./RowMenu"

type Filter = "action" | "posting" | "all"

function statusOf(r: QueueRow): { text: string; cls: string } {
  if (r.payment) {
    const s = r.payment.item_status
    if (s === "queued") return { text: "In today's payments", cls: "text-rt-magenta" }
    if (s === "pending") return { text: "Payment sending", cls: "text-rt-amber" }
    if (s === "unclaimed") return { text: "Sent — waiting for them to claim", cls: "text-rt-amber" }
    return { text: "Payment refunded/reversed — check PayPal", cls: "text-rt-red" }
  }
  if (r.reason === "trusted_unconfirmed") return { text: "Not confirmed yet", cls: "text-rt-fg-secondary" }
  if (r.reason === "posts_incomplete") return { text: "Still posting", cls: "text-rt-fg-tertiary" }
  if (r.reason === "trusted_confirmed") return { text: "Confirmed — owed", cls: "text-rt-green" }
  if (r.reason === "manual") return { text: "Owed (paying early)", cls: "text-rt-green" }
  return { text: "All posts in — owed", cls: "text-rt-green" }
}

const needsAction = (r: QueueRow) =>
  !r.payment && (r.reason === "trusted_unconfirmed" || ["posts_complete", "trusted_confirmed", "manual"].includes(r.reason))

const isOwed = (r: QueueRow) => !r.payment && ["posts_complete", "trusted_confirmed", "manual"].includes(r.reason)

interface Actions {
  pay: (r: QueueRow) => void
  confirm: (r: QueueRow, thenPay: boolean) => void
  removeFromToday: (r: QueueRow) => void
  busy: boolean
}

function RowButtons({ r, a }: { r: QueueRow; a: Actions }) {
  const btn = "rounded-md px-3 py-1 text-xs font-semibold disabled:opacity-40"
  const payable = !r.destination_issue && r.amount > 0
  if (r.payment?.item_status === "queued") {
    return (
      <button type="button" disabled={a.busy} onClick={() => a.removeFromToday(r)} className="text-xs text-rt-fg-tertiary hover:underline">
        Remove from today
      </button>
    )
  }
  if (r.payment) return null
  if (r.reason === "trusted_unconfirmed") {
    return (
      <div className="flex justify-end gap-2">
        <button type="button" disabled={a.busy} onClick={() => a.confirm(r, false)} className={`${btn} border border-white/15 text-rt-fg`}>
          Confirm
        </button>
        <button
          type="button"
          disabled={a.busy || !payable}
          title={payable ? "" : "Add their payment info first"}
          onClick={() => a.confirm(r, true)}
          className={`${btn} bg-rt-magenta text-white`}
        >
          Confirm &amp; pay
        </button>
      </div>
    )
  }
  if (isOwed(r)) {
    return (
      <button
        type="button"
        disabled={a.busy || !payable}
        title={payable ? "" : r.amount > 0 ? "Add their payment info first" : "This booking has no rate"}
        onClick={() => a.pay(r)}
        className={`${btn} bg-rt-magenta text-white`}
      >
        Pay {money(r.amount)}
      </button>
    )
  }
  return null
}

function CampaignCard({ title, rows, adminKey, a, refresh }: {
  title: string
  rows: QueueRow[]
  adminKey: string
  a: Actions
  refresh: () => void
}) {
  const owed = rows.filter(isOwed)
  const toConfirm = rows.filter((r) => r.reason === "trusted_unconfirmed" && !r.payment)
  return (
    <section className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
      <header className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3 border-b border-white/8">
        <h3 className="text-sm font-semibold text-rt-fg">{title}</h3>
        <span className="text-xs text-rt-fg-tertiary">
          {owed.length > 0 && <span className="text-rt-green">{owed.length} owed · {money(owed.reduce((t, r) => t + r.amount, 0))}</span>}
          {owed.length > 0 && toConfirm.length > 0 && " · "}
          {toConfirm.length > 0 && <span>{toConfirm.length} to confirm</span>}
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-[11px] uppercase tracking-wider text-rt-fg-tertiary">
            <tr>
              <th className="px-4 py-2 font-semibold">Creator</th>
              <th className="px-4 py-2 font-semibold">Posts</th>
              <th className="px-4 py-2 font-semibold">Rate</th>
              <th className="px-4 py-2 font-semibold">Paid to</th>
              <th className="px-4 py-2 font-semibold">Status</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const st = statusOf(r)
              return (
                <tr key={`${r.username}-${r.platform}`} className="border-t border-white/5 align-top hover:bg-white/[0.03]">
                  <td className="px-4 py-2.5">
                    <div className="text-rt-fg">@{r.handle}</div>
                    <div className="text-[11px] text-rt-fg-tertiary">
                      {r.trusted ? "Trusted" : "New"} · {r.platform === "instagram" ? "IG" : "TikTok"}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-rt-fg-secondary whitespace-nowrap">
                    {r.posts_done} / {r.posts_owed}
                  </td>
                  <td className="px-4 py-2.5 text-rt-fg whitespace-nowrap">{money(r.amount)}</td>
                  <td className="px-4 py-2.5">
                    <DestinationCell
                      key={`${r.method}-${r.destination}-${r.booking_destination}`}
                      row={r}
                      adminKey={adminKey}
                      onSaved={refresh}
                    />
                  </td>
                  <td className={`px-4 py-2.5 text-xs ${st.cls}`}>{st.text}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <div className="flex items-start justify-end gap-2">
                      <RowButtons r={r} a={a} />
                      <RowMenu row={r} adminKey={adminKey} onChanged={refresh} />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function CampaignPayouts({ adminKey }: { adminKey: string }) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<Filter>("action")
  const queue = useQuery({
    queryKey: ["payouts", "queue", adminKey],
    queryFn: () => payoutAdmin.queue(adminKey),
    retry: false,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ["payouts"] })
  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : "Request failed")

  const pay = useMutation({
    mutationFn: (r: QueueRow) => payoutAdmin.addBooking(adminKey, r),
    onSuccess: (_d, r) => {
      toast.success(`@${r.handle} added to today's payments`)
      refresh()
    },
    onError,
  })
  const confirm = useMutation({
    mutationFn: async ({ r, thenPay }: { r: QueueRow; thenPay: boolean }) => {
      await payoutAdmin.markBooking(adminKey, r, "confirm")
      if (thenPay) await payoutAdmin.addBooking(adminKey, r)
    },
    onSuccess: (_d, { r, thenPay }) => {
      toast.success(thenPay ? `@${r.handle} confirmed and added to today's payments` : `@${r.handle} confirmed`)
      refresh()
    },
    onError: (e) => {
      onError(e)
      refresh()
    },
  })
  const removeFromToday = useMutation({
    mutationFn: (r: QueueRow) => payoutAdmin.removeItem(adminKey, r.payment!.item_id),
    onSuccess: refresh,
    onError,
  })

  const groups = useMemo(() => {
    const q = queue.data
    if (!q) return []
    const all = [...q.in_batch, ...q.ready, ...q.awaiting_confirmation, ...q.not_ready]
    const keep = (r: QueueRow) =>
      filter === "all" ? true : filter === "posting" ? r.reason === "posts_incomplete" && !r.payment : needsAction(r) || Boolean(r.payment)
    const bySlug = new Map<string, { title: string; start: string; rows: QueueRow[] }>()
    for (const r of all.filter(keep)) {
      const g = bySlug.get(r.slug) ?? { title: r.campaign, start: r.start_date, rows: [] }
      g.rows.push(r)
      bySlug.set(r.slug, g)
    }
    return [...bySlug.entries()].sort(([, a], [, b]) => b.start.localeCompare(a.start))
  }, [queue.data, filter])

  if (queue.isLoading) return <p className="text-sm text-rt-fg-tertiary">Loading…</p>
  if (queue.error) return <p className="text-sm text-rt-red">{queue.error.message}</p>
  const q = queue.data
  if (!q) return null

  const owedRows = [...q.ready]
  const owedTotal = owedRows.reduce((t, r) => t + r.amount, 0)
  const actions: Actions = {
    pay: (r) => pay.mutate(r),
    confirm: (r, thenPay) => confirm.mutate({ r, thenPay }),
    removeFromToday: (r) => removeFromToday.mutate(r),
    busy: pay.isPending || confirm.isPending || removeFromToday.isPending,
  }
  const chip = (f: Filter, label: string) => (
    <button
      type="button"
      onClick={() => setFilter(f)}
      className={`rounded-full px-3 py-1 text-xs ${filter === f ? "bg-rt-magenta/15 text-rt-fg ring-1 ring-rt-magenta" : "bg-white/5 text-rt-fg-tertiary hover:text-rt-fg"}`}
    >
      {label}
    </button>
  )

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-rt-fg">Creators by campaign</h2>
          <p className="text-xs text-rt-fg-tertiary">
            New creators are owed once all posts are in. Trusted creators ({q.trusted_min_campaigns}+ campaigns) are
            paid up front — confirm they accepted, then pay.
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-semibold text-rt-fg">{money(owedTotal)} owed</div>
          <div className="text-xs text-rt-fg-tertiary">
            {owedRows.length} owed · {q.awaiting_confirmation.length} to confirm · {q.not_ready.length} still posting
          </div>
        </div>
      </div>

      <div className="flex gap-2">
        {chip("action", "Needs action")}
        {chip("posting", "Still posting")}
        {chip("all", "All")}
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-rt-fg-tertiary">Nothing here right now.</p>
      ) : (
        groups.map(([slug, g]) => (
          <CampaignCard key={slug} title={g.title} rows={g.rows} adminKey={adminKey} a={actions} refresh={refresh} />
        ))
      )}
    </section>
  )
}
