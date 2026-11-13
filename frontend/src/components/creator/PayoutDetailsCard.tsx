// Payment details form on the creator dashboard. Shows only masked details
// back to the creator; saving goes through the token-authenticated endpoint.
import { useState } from "react"
import type { FormEvent } from "react"
import { METHOD_LABEL, PAYOUT_METHODS, payoutPublic } from "@/lib/payouts"
import type { PayoutMethod, PayoutPublicView } from "@/lib/payouts"

interface Props {
  token: string
  view: PayoutPublicView
  onSaved: (view: PayoutPublicView) => void
}

export function PayoutDetailsCard({ token, view, onSaved }: Props) {
  const hasDetails = Boolean(view.destination_masked)
  const [editing, setEditing] = useState(!hasDetails)
  const [method, setMethod] = useState<PayoutMethod>(view.method || "paypal")
  const [destination, setDestination] = useState("")
  const [error, setError] = useState("")
  const [saving, setSaving] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!destination.trim()) {
      setError("Enter where you'd like to be paid.")
      return
    }
    setSaving(true)
    setError("")
    try {
      const res = await payoutPublic.submit(token, method, destination)
      onSaved(res)
      setDestination("")
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.")
    } finally {
      setSaving(false)
    }
  }

  const placeholder = PAYOUT_METHODS.find((m) => m.value === method)?.placeholder ?? ""

  return (
    <section className="rounded-xl bg-rt-bg-card border border-white/8 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-rt-fg-tertiary mb-3">Payment details</h2>

      {!editing && (
        <div role="status">
          <p className="text-sm text-rt-fg">
            {METHOD_LABEL[view.method] ?? view.method} · <span className="font-mono">{view.destination_masked}</span>
            {view.confirmed ? <span className="ml-2 text-rt-green">✓ confirmed</span> : null}
          </p>
          {!view.confirmed && (
            <p className="text-xs text-rt-amber mt-1">We have this on file from before — re-enter it to confirm it's right.</p>
          )}
          <button type="button" onClick={() => setEditing(true)} className="mt-3 text-sm text-rt-magenta hover:underline">
            {view.confirmed ? "Change payment details" : "Confirm or update"}
          </button>
        </div>
      )}

      {editing && (
        <form onSubmit={onSubmit} noValidate>
          <fieldset className="mb-4">
            <legend className="sr-only">Method</legend>
            <div className="grid grid-cols-2 gap-2">
              {PAYOUT_METHODS.map((m) => (
                <label
                  key={m.value}
                  className={`cursor-pointer rounded-md border px-3 py-2.5 text-sm text-center transition-colors ${
                    method === m.value
                      ? "border-rt-magenta bg-rt-magenta/10 text-rt-fg"
                      : "border-white/10 text-rt-fg-secondary hover:border-white/25"
                  }`}
                >
                  <input
                    type="radio"
                    name="method"
                    value={m.value}
                    checked={method === m.value}
                    onChange={() => {
                      setMethod(m.value)
                      setError("")
                    }}
                    className="sr-only"
                  />
                  {m.label}
                </label>
              ))}
            </div>
          </fieldset>

          <label className="block mb-4">
            <span className="block text-xs text-rt-fg-tertiary mb-2">Where should we send it?</span>
            <input
              type={method === "paypal" ? "email" : "text"}
              inputMode={method === "paypal" ? "email" : "text"}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              maxLength={255}
              value={destination}
              onChange={(e) => {
                setDestination(e.target.value)
                setError("")
              }}
              placeholder={placeholder}
              aria-invalid={Boolean(error)}
              className="w-full rounded-md border border-white/10 bg-rt-bg-black px-3 py-2.5 text-base text-rt-fg placeholder:text-rt-fg-tertiary focus:border-rt-magenta focus:outline-none"
            />
          </label>

          {error && (
            <p className="text-sm text-rt-red mb-4" role="alert">
              {error}
            </p>
          )}

          <div className="flex items-center gap-4">
            <button
              type="submit"
              disabled={saving}
              className="flex-1 rounded-md bg-rt-magenta px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
            >
              {saving ? "Saving…" : "Confirm"}
            </button>
            {hasDetails && (
              <button type="button" onClick={() => setEditing(false)} className="text-sm text-rt-fg-tertiary">
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  )
}
