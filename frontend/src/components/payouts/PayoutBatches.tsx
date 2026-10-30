// Daily payout batch: build from the Ready list, review, type the total to
// approve. PayPal/Venmo go out through PayPal; Cash App / other are paid by
// hand from the checklist, then marked paid here.
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { METHOD_LABEL, money, payoutAdmin } from "@/lib/payouts"
import type { BatchItem, PayoutBatch } from "@/lib/payouts"

const ITEM_STATUS: Record<BatchItem["status"], { label: string; cls: string }> = {
  queued: { label: "In draft", cls: "text-rt-fg-tertiary" },
  pending: { label: "Sending", cls: "text-rt-amber" },
  succeeded: { label: "Paid ✓", cls: "text-rt-green" },
  failed: { label: "Failed — back in queue", cls: "text-rt-red" },
  unclaimed: { label: "Unclaimed — creator must accept", cls: "text-rt-amber" },
  review: { label: "Refunded/reversed — check PayPal", cls: "text-rt-red" },
  sandbox_ok: { label: "Sandbox test OK (not marked paid)", cls: "text-rt-amber" },
  removed: { label: "Removed", cls: "text-rt-fg-tertiary" },
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success("Copied")
  } catch {
    toast.error("Clipboard blocked")
  }
}

function ItemRow({ item, draft, onRemove, onMarkPaid }: {
  item: BatchItem
  draft: boolean
  onRemove: (id: number) => void
  onMarkPaid: (id: number) => void
}) {
  const st = ITEM_STATUS[item.status]
  const manualPending = item.lane === "manual" && item.status === "pending"
  return (
    <tr className="border-t border-white/5 align-top">
      <td className="px-3 py-2 text-rt-fg">
        @{item.username}
        <div className="text-xs text-rt-fg-tertiary">{item.campaign}</div>
      </td>
      <td className="px-3 py-2 text-xs text-rt-fg-secondary">
        {METHOD_LABEL[item.method] ?? item.method}{" "}
        <button type="button" className="font-mono hover:text-rt-fg" onClick={() => copy(item.destination)} title="Copy">
          {item.destination}
        </button>
      </td>
      <td className="px-3 py-2 text-right text-rt-fg whitespace-nowrap">
        <button type="button" onClick={() => copy(item.amount.toFixed(2))} title="Copy amount">
          {money(item.amount)}
        </button>
      </td>
      <td className={`px-3 py-2 text-xs ${st.cls}`}>
        {st.label}
        {item.error && <div className="text-rt-red">{item.error}</div>}
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {draft && (
          <button type="button" className="text-xs text-rt-fg-tertiary hover:underline" onClick={() => onRemove(item.id)}>
            Remove
          </button>
        )}
        {manualPending && (
          <button type="button" className="text-xs text-rt-green hover:underline" onClick={() => onMarkPaid(item.id)}>
            I sent it — mark paid
          </button>
        )}
      </td>
    </tr>
  )
}

function ItemTable(props: { items: BatchItem[]; draft: boolean; onRemove: (id: number) => void; onMarkPaid: (id: number) => void }) {
  if (!props.items.length) return <p className="text-xs text-rt-fg-tertiary">None.</p>
  return (
    <div className="overflow-x-auto rounded-lg border border-white/8">
      <table className="w-full text-sm">
        <tbody>
          {props.items.map((i) => (
            <ItemRow key={i.id} item={i} draft={props.draft} onRemove={props.onRemove} onMarkPaid={props.onMarkPaid} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BatchCard({ batch, adminKey, paypalConnected }: { batch: PayoutBatch; adminKey: string; paypalConnected: boolean }) {
  const qc = useQueryClient()
  const [typed, setTyped] = useState("")
  const refresh = () => qc.invalidateQueries({ queryKey: ["payouts"] })
  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : "Request failed")
  const opts = { onSuccess: refresh, onError }

  const approve = useMutation({ mutationFn: () => payoutAdmin.approveBatch(adminKey, batch.id, typed), ...opts })
  const cancel = useMutation({ mutationFn: () => payoutAdmin.cancelBatch(adminKey, batch.id), ...opts })
  const sync = useMutation({ mutationFn: () => payoutAdmin.syncBatch(adminKey, batch.id), ...opts })
  const remove = useMutation({ mutationFn: (id: number) => payoutAdmin.removeItem(adminKey, id), ...opts })
  const markPaid = useMutation({ mutationFn: (id: number) => payoutAdmin.markItemPaid(adminKey, id), ...opts })

  const draft = batch.status === "draft" || batch.status === "sending"
  const api = batch.items.filter((i) => i.lane === "api")
  const manual = batch.items.filter((i) => i.lane === "manual")
  const tableProps = { draft: batch.status === "draft", onRemove: remove.mutate, onMarkPaid: markPaid.mutate }

  return (
    <div className="rounded-xl bg-rt-bg-card border border-white/8 p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-rt-fg">
          Batch #{batch.id} · {new Date(batch.created_at).toLocaleDateString()} ·{" "}
          <span className="uppercase text-xs tracking-wider text-rt-fg-tertiary">{batch.status}</span>
          {batch.paypal_env === "sandbox" && <span className="ml-2 text-xs text-rt-amber">SANDBOX — test money</span>}
        </div>
        <div className="text-sm text-rt-fg">{money(batch.totals.all)}</div>
      </div>
      {batch.error && <p className="text-sm text-rt-red">{batch.error}</p>}

      <div className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-rt-fg-tertiary">
          PayPal + Venmo (sent automatically) · {money(batch.totals.api)}
        </h4>
        <ItemTable items={api} {...tableProps} />
      </div>
      <div className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-rt-fg-tertiary">
          Cash App / other (pay by hand, then mark paid) · {money(batch.totals.manual)}
        </h4>
        <ItemTable items={manual} {...tableProps} />
      </div>

      {draft && (
        <div className="rounded-lg border border-rt-magenta/30 p-3 space-y-2">
          {api.length > 0 && !paypalConnected ? (
            <p className="text-sm text-rt-amber">PayPal isn't connected yet — remove PayPal/Venmo items or connect PayPal to send.</p>
          ) : (
            <p className="text-sm text-rt-fg-secondary">
              To approve, type the PayPal/Venmo total: <b className="text-rt-fg">{batch.totals.api.toFixed(2)}</b>
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              inputMode="decimal"
              placeholder="0.00"
              className="w-32 rounded-md border border-white/10 bg-rt-bg-black px-3 py-1.5 text-sm text-rt-fg"
            />
            <button
              type="button"
              disabled={!typed || approve.isPending}
              onClick={() => approve.mutate()}
              className="rounded-md bg-rt-magenta px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
            >
              {approve.isPending ? "Sending…" : "Approve & send"}
            </button>
            {batch.status === "draft" && (
              <button type="button" onClick={() => cancel.mutate()} className="text-sm text-rt-fg-tertiary hover:underline">
                Cancel batch
              </button>
            )}
          </div>
        </div>
      )}

      {batch.status === "sent" && api.length > 0 && (
        <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}
          className="text-sm text-rt-magenta hover:underline">
          {sync.isPending ? "Checking PayPal…" : "Refresh PayPal status"}
        </button>
      )}
    </div>
  )
}

export function PayoutBatches({ adminKey }: { adminKey: string }) {
  const qc = useQueryClient()
  const [showHistory, setShowHistory] = useState(false)
  const data = useQuery({
    queryKey: ["payouts", "batches", adminKey],
    queryFn: () => payoutAdmin.batches(adminKey),
    retry: false,
  })
  const create = useMutation({
    mutationFn: () => payoutAdmin.createBatch(adminKey),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payouts"] }),
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't build batch"),
  })

  if (data.isLoading) return null
  if (data.error) return <p className="text-sm text-rt-red">{data.error.message}</p>
  const d = data.data
  if (!d) return null

  const open = d.batches.filter((b) => ["draft", "sending", "sent"].includes(b.status))
  const past = d.batches.filter((b) => b.status === "closed")

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-rt-fg">Payout batches</h2>
          <p className="text-xs text-rt-fg-tertiary">
            PayPal:{" "}
            {d.paypal.connected ? (
              <span className={d.paypal.env === "live" ? "text-rt-green" : "text-rt-amber"}>
                connected ({d.paypal.env === "live" ? "LIVE" : "sandbox — test money only"})
              </span>
            ) : (
              <span className="text-rt-amber">not connected</span>
            )}
          </p>
        </div>
        {!open.some((b) => b.status !== "sent") && (
          <button
            type="button"
            onClick={() => create.mutate()}
            disabled={create.isPending}
            className="rounded-md bg-rt-magenta px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {create.isPending ? "Building…" : "Build today's batch"}
          </button>
        )}
      </div>

      {open.map((b) => (
        <BatchCard key={b.id} batch={b} adminKey={adminKey} paypalConnected={d.paypal.connected} />
      ))}

      {past.length > 0 && (
        <div className="space-y-2">
          <button type="button" onClick={() => setShowHistory((v) => !v)} className="text-sm text-rt-fg-secondary">
            {showHistory ? "▾" : "▸"} Past batches ({past.length})
          </button>
          {showHistory &&
            past.map((b) => <BatchCard key={b.id} batch={b} adminKey={adminKey} paypalConnected={d.paypal.connected} />)}
        </div>
      )}
    </section>
  )
}
