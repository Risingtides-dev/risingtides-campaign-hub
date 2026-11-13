// "Paid to" cell: shows a creator's payment details, lets Jake fix them
// inline, and offers the old booking email as a one-click "Use this".
import { useState } from "react"
import { toast } from "sonner"
import { METHOD_LABEL, PAYOUT_METHODS, guessMethod, payoutAdmin } from "@/lib/payouts"
import type { PayoutMethod, QueueRow } from "@/lib/payouts"

const ISSUE_TEXT: Record<string, { text: string; cls: string }> = {
  missing: { text: "No payment info", cls: "text-rt-red" },
  changed: { text: "Changed by creator — check before paying", cls: "text-rt-red" },
  unconfirmed: { text: "Not confirmed", cls: "text-rt-amber" },
}

interface Props {
  row: QueueRow
  adminKey: string
  onSaved: () => void
}

export function DestinationCell({ row, adminKey, onSaved }: Props) {
  const [editing, setEditing] = useState(false)
  const [method, setMethod] = useState<PayoutMethod>(row.method || guessMethod(row.booking_destination))
  const [value, setValue] = useState(row.destination || row.booking_destination)
  const [saving, setSaving] = useState(false)

  const save = async (m: PayoutMethod, v: string) => {
    setSaving(true)
    try {
      await payoutAdmin.setDestination(adminKey, row.username, m, v)
      toast.success(`Saved @${row.handle}'s payment info`)
      setEditing(false)
      onSaved()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save")
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <form
        className="flex flex-wrap items-center gap-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          void save(method, value)
        }}
      >
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value as PayoutMethod)}
          className="rounded border border-white/10 bg-rt-bg-black px-1.5 py-1 text-xs text-rt-fg"
        >
          {PAYOUT_METHODS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoFocus
          className="w-44 rounded border border-white/10 bg-rt-bg-black px-2 py-1 text-xs text-rt-fg font-mono"
        />
        <button type="submit" disabled={saving} className="text-xs text-rt-green hover:underline">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="text-xs text-rt-fg-tertiary">
          Cancel
        </button>
      </form>
    )
  }

  const issue = ISSUE_TEXT[row.destination_issue]
  return (
    <div className="text-xs">
      {row.destination ? (
        <span className="text-rt-fg-secondary">
          {METHOD_LABEL[row.method] ?? row.method} <span className="font-mono">{row.destination}</span>
        </span>
      ) : null}
      {issue && <div className={issue.cls}>{issue.text}</div>}
      {row.booking_destination && (
        <div className="text-rt-fg-tertiary">
          On booking: <span className="font-mono">{row.booking_destination}</span>{" "}
          <button
            type="button"
            disabled={saving}
            onClick={() => save(guessMethod(row.booking_destination), row.booking_destination)}
            className="text-rt-magenta hover:underline"
          >
            Use this
          </button>
        </div>
      )}
      <button type="button" onClick={() => setEditing(true)} className="text-rt-fg-tertiary hover:text-rt-fg">
        ✎ {row.destination ? "Edit" : "Add"}
      </button>
    </div>
  )
}
