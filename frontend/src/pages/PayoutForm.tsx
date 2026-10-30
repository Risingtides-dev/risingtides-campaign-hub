// Public creator page: /payout#<token>. Rendered OUTSIDE the Hub layout —
// a creator must never see the sidebar, other creators, amounts or campaigns.
import { useEffect, useState } from "react"
import type { FormEvent } from "react"
import {
  PAYOUT_METHODS,
  payoutPublic,
  readTokenFromHash,
} from "@/lib/payouts"
import type { PayoutMethod, PayoutPublicView } from "@/lib/payouts"

type Phase = "loading" | "invalid" | "form" | "done"

const METHOD_LABEL = Object.fromEntries(PAYOUT_METHODS.map((m) => [m.value, m.label]))

export default function PayoutForm() {
  const [token] = useState(readTokenFromHash)
  const [phase, setPhase] = useState<Phase>(token ? "loading" : "invalid")
  const [view, setView] = useState<PayoutPublicView | null>(null)
  const [method, setMethod] = useState<PayoutMethod>("paypal")
  const [destination, setDestination] = useState("")
  const [error, setError] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    payoutPublic
      .lookup(token)
      .then((v) => {
        if (cancelled) return
        setView(v)
        if (v.method) setMethod(v.method)
        setPhase("form")
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
      setView(res)
      setPhase("done")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Try again.")
    } finally {
      setSaving(false)
    }
  }

  const placeholder = PAYOUT_METHODS.find((m) => m.value === method)?.placeholder ?? ""

  return (
    <div className="min-h-screen bg-rt-bg-black flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md rounded-xl bg-rt-bg-card border border-white/8 p-6 sm:p-8">
        <div className="text-sm font-bold font-display rt-gradient-text mb-6">Rising Tides</div>

        {phase === "loading" && <p className="text-rt-fg-secondary text-sm">Loading…</p>}

        {phase === "invalid" && (
          <p className="text-rt-fg text-sm" role="alert">
            {error || "This link isn't valid anymore. Message us and we'll send you a fresh one."}
          </p>
        )}

        {phase === "done" && view && (
          <div role="status">
            <h1 className="text-xl font-semibold text-rt-fg mb-2">You're all set 🙌</h1>
            <p className="text-rt-fg-secondary text-sm">
              We'll pay you via <b className="text-rt-fg">{METHOD_LABEL[view.method] ?? view.method}</b>{" "}
              ({view.destination_masked}) once all your posts are up — usually within 1–2 business days.
            </p>
            <button
              type="button"
              onClick={() => {
                setDestination("")
                setPhase("form")
              }}
              className="mt-6 text-sm text-rt-magenta hover:underline"
            >
              Made a typo? Update it
            </button>
          </div>
        )}

        {phase === "form" && view && (
          <form onSubmit={onSubmit} noValidate>
            <h1 className="text-xl font-semibold text-rt-fg mb-2">Hey @{view.handle} 👋</h1>
            <p className="text-rt-fg-secondary text-sm mb-6">
              Drop your payment info so we can pay you as soon as your posts are verified.
            </p>

            {view.destination_masked && (
              <p className="text-xs text-rt-fg-tertiary mb-4">
                On file: {METHOD_LABEL[view.method] ?? view.method} {view.destination_masked}
                {view.confirmed ? " (confirmed)" : " — re-enter it below to confirm, or enter a new one"}
              </p>
            )}

            <fieldset className="mb-4">
              <legend className="text-xs font-semibold uppercase tracking-wider text-rt-fg-tertiary mb-2">
                Method
              </legend>
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
              <span className="block text-xs font-semibold uppercase tracking-wider text-rt-fg-tertiary mb-2">
                Where should we send it?
              </span>
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

            <button
              type="submit"
              disabled={saving}
              className="w-full rounded-md bg-rt-magenta px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
            >
              {saving ? "Saving…" : "Confirm"}
            </button>
            <p className="mt-4 text-xs text-rt-fg-tertiary">
              Only you can see this page. Don't share this link.
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
