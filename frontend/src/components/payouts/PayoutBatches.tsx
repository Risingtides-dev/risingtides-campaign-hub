import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { METHOD_LABEL, money, payoutAdmin } from "@/lib/payouts"
import { usePayoutSessionIsActive, usePayoutSessionPrefix } from "@/lib/payoutSession"
import type { BatchItem, PayoutBatch } from "@/lib/payouts"

const ITEM_STATUS: Record<BatchItem["status"], { label: string; cls: string }> = {
  queued: { label: "Queued", cls: "text-rt-fg-tertiary" },
  pending: { label: "Pending", cls: "text-rt-amber" },
  succeeded: { label: "Paid", cls: "text-rt-green" },
  failed: { label: "Failed", cls: "text-rt-red" },
  unclaimed: { label: "Unclaimed", cls: "text-rt-amber" },
  review: { label: "Needs review", cls: "text-rt-red" },
  sandbox_ok: { label: "Test succeeded", cls: "text-rt-amber" },
  removed: { label: "Removed", cls: "text-rt-fg-tertiary" },
}

function batchSummary(batch: PayoutBatch, unknown: boolean) {
  const items = batch.items.filter((item) => item.status !== "removed")
  const amounts = { paid: 0, failed: 0, test: 0, review: 0, pending: 0 }
  for (const item of items) {
    const category = item.status === "succeeded" ? (item.lane === "api" && batch.paypal_env === "sandbox" ? "test" : "paid")
      : item.status === "failed" ? "failed" : item.status === "sandbox_ok" ? "test"
        : item.status === "review" ? "review" : "pending"
    amounts[category] += item.amount
  }
  const label = batch.status === "cancelled" ? "Cancelled batch"
    : unknown ? "Awaiting reconciliation"
      : batch.status === "draft" ? "Draft batch"
        : amounts.review > 0 ? "Needs review"
          : amounts.paid > 0 && amounts.test === 0 && items.every((item) => item.status === "succeeded") ? "Paid"
            : amounts.paid > 0 ? "Partially paid"
              : amounts.test > 0 ? "Sandbox results"
                : items.length > 0 && items.every((item) => item.status === "failed") ? "Failed batch"
                  : items.length === 0 ? "Empty batch" : "Payments pending"
  return { label, amounts }
}

function confirmationMatches(value: string, total: number): boolean {
  const text = value.trim()
  return /^\d+(?:\.\d{1,2})?$/.test(text) && Number.isFinite(total) && total > 0
    && Math.round(Number(text) * 100) === Math.round(total * 100)
}

async function readBatches(adminKey: string, signal: AbortSignal, isActive: () => boolean) {
  if (!isActive() || signal.aborted) throw new Error("Payout session ended")
  const result = await payoutAdmin.batches(adminKey, signal)
  if (!isActive() || signal.aborted) throw new Error("Payout session ended")
  return result
}

function ItemRow({ item, draft, busy, paypalEnv, manualEnabled, onRemove, onMarkPaid }: {
  item: BatchItem
  draft: boolean
  busy: boolean
  paypalEnv: string
  manualEnabled: boolean
  onRemove: (id: number) => void
  onMarkPaid: (id: number) => void
}) {
  const isActive = usePayoutSessionIsActive()
  const st = item.lane === "api" && paypalEnv === "sandbox" && item.status === "succeeded"
    ? ITEM_STATUS.sandbox_ok : ITEM_STATUS[item.status] ?? ITEM_STATUS.review
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      if (isActive()) toast.success("Copied")
    } catch {
      if (isActive()) toast.error("Clipboard blocked")
    }
  }
  return (
    <tr className="border-t border-white/5 align-top">
      <td className="px-3 py-2 text-rt-fg">
        @{item.username}
        <div className="text-xs text-rt-fg-tertiary">{item.campaign}</div>
      </td>
      <td className="px-3 py-2 text-xs text-rt-fg-secondary">
        {METHOD_LABEL[item.method] ?? item.method}{" "}
        <button type="button" className="font-mono hover:text-rt-fg" onClick={() => void copy(item.destination)} title="Copy">
          {item.destination}
        </button>
      </td>
      <td className="px-3 py-2 text-right text-rt-fg whitespace-nowrap">
        <button type="button" onClick={() => void copy(item.amount.toFixed(2))} title="Copy amount">
          {money(item.amount)}
        </button>
      </td>
      <td className={`px-3 py-2 text-xs ${st.cls}`}>
        {st.label}
        {item.error && <div className="text-rt-red">{item.error}</div>}
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {draft && <button type="button" disabled={busy} className="text-xs text-rt-fg-tertiary hover:underline" onClick={() => onRemove(item.id)}>Remove</button>}
        {manualEnabled && item.lane === "manual" && item.status === "pending" && (
          <button type="button" disabled={busy} className="text-xs text-rt-green hover:underline" onClick={() => onMarkPaid(item.id)}>
            Mark paid manually
          </button>
        )}
      </td>
    </tr>
  )
}

function ItemTable(props: { items: BatchItem[]; draft: boolean; busy: boolean; paypalEnv: string; manualEnabled: boolean; onRemove: (id: number) => void; onMarkPaid: (id: number) => void }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-white/8">
      <table className="w-full text-sm">
        <tbody>{props.items.map((item) => <ItemRow key={item.id} {...props} item={item} />)}</tbody>
      </table>
    </div>
  )
}

function BatchCard({ batch, adminKey, paypalConfigured }: { batch: PayoutBatch; adminKey: string; paypalConfigured: boolean }) {
  const qc = useQueryClient()
  const prefix = usePayoutSessionPrefix()
  const isActive = usePayoutSessionIsActive()
  const [typed, setTyped] = useState("")
  const [receipt, setReceipt] = useState("")
  const [approvalUncertain, setApprovalUncertain] = useState(false)
  const refresh = () => isActive() ? qc.invalidateQueries({ queryKey: prefix }) : Promise.resolve()
  const onError = (error: unknown) => {
    if (isActive()) toast.error(error instanceof Error ? error.message : "Request failed")
  }
  const opts = { retry: false, onSuccess: refresh, onError }
  const request = <T,>(operation: () => Promise<T>) => isActive() ? operation() : Promise.reject(new Error("Payout session ended"))
  const approve = useMutation({
    mutationKey: [...prefix, "approve-batch", batch.id],
    retry: false,
    mutationFn: () => request(() => payoutAdmin.approveBatch(adminKey, batch.id, batch.totals.api === 0 ? "0" : typed.trim())),
    onSuccess: refresh,
    onError: async (error) => {
      if (!isActive()) return
      // The error status alone cannot distinguish a refused approval from a
      // provider POST whose response was lost. Only a new DB read can do so.
      setApprovalUncertain(true)
      onError(error)
      const queryKey = [...prefix, "batches"]
      try {
        await qc.cancelQueries({ queryKey, exact: true })
        if (!isActive()) return
        const latest = await qc.fetchQuery({
          queryKey,
          queryFn: ({ signal }) => readBatches(adminKey, signal, isActive),
          staleTime: 0,
          retry: false,
        })
        if (isActive() && latest.batches.find((item) => item.id === batch.id)?.status === "draft") {
          setApprovalUncertain(false)
        }
      } catch {
        // Failed proof keeps approval held. The parent exposes a GET-only retry.
      }
    },
  })
  const cancel = useMutation({ mutationKey: [...prefix, "cancel-batch", batch.id], mutationFn: () => request(() => payoutAdmin.cancelBatch(adminKey, batch.id)), ...opts })
  const sync = useMutation({ mutationKey: [...prefix, "sync-batch", batch.id], mutationFn: () => request(() => payoutAdmin.syncBatch(adminKey, batch.id)), ...opts })
  const reconcile = useMutation({
    mutationKey: [...prefix, "reconcile-batch", batch.id],
    retry: false,
    mutationFn: () => request(() => payoutAdmin.reconcileBatch(adminKey, batch.id, (batch.paypal_batch_id || receipt).trim())),
    onSuccess: () => {
      if (!isActive()) return
      setApprovalUncertain(false)
      return refresh()
    },
    onError,
  })
  const remove = useMutation({ mutationKey: [...prefix, "remove-item", batch.id], mutationFn: (id: number) => request(() => payoutAdmin.removeItem(adminKey, id)), ...opts })
  const markPaid = useMutation({ mutationKey: [...prefix, "mark-paid", batch.id], mutationFn: (id: number) => request(() => payoutAdmin.markItemPaid(adminKey, id)), ...opts })
  const busy = approve.isPending || cancel.isPending || sync.isPending || reconcile.isPending || remove.isPending || markPaid.isPending
  const unknown = batch.status === "sending" || approvalUncertain
  const draft = batch.status === "draft" && !unknown
  const api = batch.items.filter((item) => item.lane === "api" && item.status !== "removed")
  const manual = batch.items.filter((item) => item.lane === "manual" && item.status !== "removed")
  const summary = batchSummary(batch, unknown)
  const tableProps = { draft, busy, paypalEnv: batch.paypal_env, manualEnabled: !unknown && ["sent", "closed"].includes(batch.status), onRemove: remove.mutate, onMarkPaid: markPaid.mutate }
  const amountLabels = Object.entries(summary.amounts).filter(([, amount]) => amount > 0)
    .map(([status, amount]) => `${status === "test" ? "Test" : status[0].toUpperCase() + status.slice(1)} ${money(amount)}`)

  return (
    <article aria-label={`Batch ${batch.id}`} className="rounded-xl bg-rt-bg-card border border-white/8 p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-rt-fg">{summary.label}</h3>
        <div className="text-sm text-rt-fg">{money(batch.totals.all)}</div>
      </div>
      {batch.paypal_env === "sandbox" && <p className="text-xs text-rt-amber">PayPal sandbox</p>}
      {!draft && amountLabels.length > 0 && <p className="text-xs text-rt-fg-secondary">{amountLabels.join(" · ")}</p>}
      {batch.error && <p role="alert" className="text-sm text-rt-red">{batch.error}</p>}
      {api.length > 0 && <div className="space-y-2">
        <h4 className="text-xs font-semibold text-rt-fg-tertiary">PayPal / Venmo · {money(batch.totals.api)}</h4>
        <ItemTable items={api} {...tableProps} />
      </div>}
      {manual.length > 0 && <div className="space-y-2">
        <h4 className="text-xs font-semibold text-rt-fg-tertiary">Manual · {money(batch.totals.manual)}</h4>
        <ItemTable items={manual} {...tableProps} />
      </div>}
      {draft && <div className="flex flex-wrap items-center gap-2">
        {api.length > 0 && <>
          <input
            aria-label={`Confirm PayPal total ${batch.totals.api.toFixed(2)} for batch ${batch.id}`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            inputMode="decimal"
            placeholder={batch.totals.api.toFixed(2)}
            disabled={busy || !paypalConfigured}
            className="w-32 rounded-md border border-white/10 bg-rt-bg-black px-3 py-1.5 text-sm text-rt-fg"
          />
          <button
            type="button"
            disabled={busy || !paypalConfigured || !confirmationMatches(typed, batch.totals.api)}
            onClick={() => approve.mutate()}
            className="rounded-md bg-rt-magenta px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
          >{approve.isPending ? "Sending…" : `Send ${money(batch.totals.api)}`}</button>
        </>}
        {api.length === 0 && manual.length > 0 && (
          <button type="button" disabled={busy} onClick={() => approve.mutate()} className="rounded-md bg-rt-magenta px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
            Start manual payments
          </button>
        )}
        <button type="button" disabled={busy} onClick={() => cancel.mutate()} className="text-xs text-rt-fg-tertiary hover:underline">Clear batch</button>
        {api.length > 0 && !paypalConfigured && <span className="text-xs text-rt-amber">PayPal is not configured.</span>}
      </div>}
      {unknown && <div className="space-y-2">
        <p className="text-sm text-rt-amber">Approval outcome is unconfirmed.</p>
        {batch.sender_batch_id && <p className="break-all font-mono text-xs text-rt-fg-secondary">Request: {batch.sender_batch_id}</p>}
        <form className="flex flex-wrap items-center gap-2" onSubmit={(event) => { event.preventDefault(); if (!busy && (batch.paypal_batch_id || receipt).trim()) reconcile.mutate() }}>
          {!batch.paypal_batch_id && <input
            aria-label={`Original PayPal batch ID for batch ${batch.id}`}
            placeholder="Original PayPal batch ID"
            value={receipt}
            disabled={busy}
            onChange={(event) => setReceipt(event.target.value)}
            className="w-64 rounded-md border border-white/10 bg-rt-bg-black px-3 py-1.5 text-sm text-rt-fg"
          />}
          {batch.paypal_batch_id && <span className="font-mono text-xs text-rt-fg-secondary">{batch.paypal_batch_id}</span>}
          <button type="submit" disabled={busy || !(batch.paypal_batch_id || receipt).trim()} className="text-sm text-rt-magenta disabled:opacity-40">
            {reconcile.isPending ? "Checking receipt…" : "Reconcile receipt"}
          </button>
        </form>
      </div>}
      {!unknown && ["sent", "closed"].includes(batch.status) && batch.paypal_batch_id && (
        <button type="button" onClick={() => sync.mutate()} disabled={busy} className="text-sm text-rt-magenta hover:underline">
          {sync.isPending ? "Checking receipt…" : "Refresh status"}
        </button>
      )}
    </article>
  )
}

export function PayoutBatches({ adminKey }: { adminKey: string }) {
  const qc = useQueryClient()
  const prefix = usePayoutSessionPrefix()
  const isActive = usePayoutSessionIsActive()
  const [showHistory, setShowHistory] = useState(false)
  const data = useQuery({
    queryKey: [...prefix, "batches"],
    queryFn: ({ signal }) => readBatches(adminKey, signal, isActive),
    retry: false,
  })
  const create = useMutation({
    mutationKey: [...prefix, "create-batch"],
    retry: false,
    mutationFn: () => isActive() ? payoutAdmin.createBatch(adminKey) : Promise.reject(new Error("Payout session ended")),
    onSuccess: () => isActive() ? qc.invalidateQueries({ queryKey: prefix }) : undefined,
    onError: (error) => { if (isActive()) toast.error(error instanceof Error ? error.message : "Couldn't build batch") },
  })
  if (data.isLoading) return <p role="status" className="text-sm text-rt-fg-tertiary">Loading batches…</p>
  if (data.error) return <div className="space-y-2">
    <p role="alert" className="text-sm text-rt-red">{data.error.message}</p>
    <button type="button" disabled={data.isFetching} onClick={() => void data.refetch()} className="text-sm text-rt-magenta disabled:opacity-40">Refresh batches</button>
  </div>
  const response = data.data
  if (!response) return null
  const open = response.batches.filter((batch) => ["draft", "sending", "sent"].includes(batch.status))
  const past = response.batches.filter((batch) => !["draft", "sending", "sent"].includes(batch.status))
  const sending = open.some((batch) => batch.status === "sending")
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-rt-fg">Payments</h2>
          <p className="text-xs text-rt-fg-tertiary">PayPal: {response.paypal.connected ? `configured (${response.paypal.env === "live" ? "LIVE" : "sandbox"})` : "not configured"}</p>
        </div>
        <button type="button" onClick={() => create.mutate()} disabled={create.isPending || sending} className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-rt-fg disabled:opacity-50">
          {create.isPending ? "Adding…" : "Queue all ready"}
        </button>
      </div>
      {open.length === 0 && <p className="text-sm text-rt-fg-tertiary">No open payment batches.</p>}
      {open.map((batch) => <BatchCard key={batch.id} batch={batch} adminKey={adminKey} paypalConfigured={response.paypal.connected} />)}
      {past.length > 0 && <div className="space-y-2">
        <button type="button" onClick={() => setShowHistory((value) => !value)} aria-expanded={showHistory} className="text-sm text-rt-fg-secondary">Past batches ({past.length})</button>
        {showHistory && past.map((batch) => <BatchCard key={batch.id} batch={batch} adminKey={adminKey} paypalConfigured={response.paypal.connected} />)}
      </div>}
    </section>
  )
}
