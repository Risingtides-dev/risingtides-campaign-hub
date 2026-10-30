// Hub admin page for creator payout details. Gated by PAYOUT_ADMIN_KEY
// because the Hub itself has no login. Changed destinations are flagged at
// the top until reviewed — the dashboard flag is the change alert.
import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { PAYOUT_METHODS, PayoutApiError, payoutAdmin } from "@/lib/payouts"
import type { PayoutAdminRow } from "@/lib/payouts"
import { PayoutHistory } from "@/components/payouts/PayoutHistory"
import { PayoutLinkGenerator } from "@/components/payouts/PayoutLinkGenerator"

const KEY_STORAGE = "rt.payoutAdminKey"
const METHOD_LABEL: Record<string, string> = Object.fromEntries(
  PAYOUT_METHODS.map((m) => [m.value, m.label]),
)

function KeyGate({ onKey }: { onKey: (k: string) => void }) {
  const [value, setValue] = useState("")
  return (
    <form
      className="max-w-sm rounded-xl bg-rt-bg-card border border-white/8 p-6"
      onSubmit={(e) => {
        e.preventDefault()
        if (value.trim()) onKey(value.trim())
      }}
    >
      <p className="text-sm text-rt-fg-secondary mb-3">
        Payment details are locked. Enter the payout admin key.
      </p>
      <input
        type="password"
        autoComplete="off"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-full rounded-md border border-white/10 bg-rt-bg-black px-3 py-2 text-sm text-rt-fg mb-3"
      />
      <button type="submit" className="rounded-md bg-rt-magenta px-4 py-2 text-sm font-semibold text-white">
        Unlock
      </button>
    </form>
  )
}

function statusOf(r: PayoutAdminRow) {
  if (r.flagged) return { label: "Changed — review", cls: "text-rt-red" }
  if (r.confirmed) return { label: "Confirmed", cls: "text-rt-green" }
  if (r.destination) return { label: "On file, unconfirmed", cls: "text-rt-amber" }
  return { label: "Missing", cls: "text-rt-fg-tertiary" }
}

function Tile({ label, value, tone = "text-rt-fg" }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg bg-rt-bg-card border border-white/8 px-4 py-3">
      <div className={`text-2xl font-semibold ${tone}`}>{value}</div>
      <div className="text-xs text-rt-fg-tertiary">{label}</div>
    </div>
  )
}

export default function Payouts() {
  const [adminKey, setAdminKey] = useState(() => sessionStorage.getItem(KEY_STORAGE) ?? "")
  const [search, setSearch] = useState("")
  const [openHistory, setOpenHistory] = useState<string | null>(null)
  const qc = useQueryClient()

  const overview = useQuery({
    queryKey: ["payouts", "overview", adminKey],
    queryFn: () => payoutAdmin.overview(adminKey),
    enabled: Boolean(adminKey),
    retry: false,
  })

  const forgetKey = () => {
    sessionStorage.removeItem(KEY_STORAGE)
    setAdminKey("")
  }
  const saveKey = (k: string) => {
    sessionStorage.setItem(KEY_STORAGE, k)
    setAdminKey(k)
  }

  const refresh = () => qc.invalidateQueries({ queryKey: ["payouts"] })
  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : "Request failed")

  const clearFlag = useMutation({
    mutationFn: (u: string) => payoutAdmin.clearFlag(adminKey, u),
    onSuccess: () => {
      toast.success("Marked reviewed")
      refresh()
    },
    onError,
  })
  const rotate = useMutation({
    mutationFn: (u: string) => payoutAdmin.rotate(adminKey, u),
    onSuccess: async (res) => {
      await navigator.clipboard.writeText(res.link).catch(() => undefined)
      toast.success(`New link for @${res.username} copied — the old one no longer works`)
      refresh()
    },
    onError,
  })

  const rows = useMemo(() => {
    const all = overview.data?.creators ?? []
    const q = search.trim().toLowerCase().replace(/^@/, "")
    return q ? all.filter((r) => r.username.includes(q)) : all
  }, [overview.data, search])

  if (!adminKey) return <div className="p-6"><KeyGate onKey={saveKey} /></div>

  const err = overview.error
  const authFailed = err instanceof PayoutApiError && [401, 503].includes(err.status)
  if (authFailed) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-rt-red">{err.message}</p>
        <button type="button" onClick={forgetKey} className="text-sm text-rt-magenta hover:underline">
          Enter a different key
        </button>
      </div>
    )
  }

  const s = overview.data?.summary
  const flagged = rows.filter((r) => r.flagged)

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold font-display text-rt-fg">Payouts</h1>
        <button type="button" onClick={forgetKey} className="text-xs text-rt-fg-tertiary hover:text-rt-fg">
          Lock
        </button>
      </div>

      {overview.isLoading && <p className="text-sm text-rt-fg-tertiary">Loading…</p>}
      {err && <p className="text-sm text-rt-red">{err.message}</p>}

      {s && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Tile label="Confirmed by creator" value={s.confirmed} tone="text-rt-green" />
          <Tile label="On file, unconfirmed" value={s.unconfirmed_on_file} tone="text-rt-amber" />
          <Tile label="Missing" value={s.missing} />
          <Tile label="Changed — needs review" value={s.flagged} tone={s.flagged ? "text-rt-red" : "text-rt-fg"} />
          <Tile label="Links issued" value={s.links_issued} />
        </div>
      )}

      {flagged.length > 0 && (
        <section className="rounded-xl border border-rt-red/40 bg-rt-red/5 p-4 space-y-3">
          <h2 className="text-sm font-semibold text-rt-red">
            {flagged.length} changed destination{flagged.length === 1 ? "" : "s"} — check with the creator before paying
          </h2>
          {flagged.map((r) => (
            <div key={r.username} className="rounded-lg bg-rt-bg-card p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm text-rt-fg">@{r.handle}</span>
                <div className="flex gap-3">
                  <button type="button" className="text-xs text-rt-fg-secondary hover:text-rt-fg"
                    onClick={() => rotate.mutate(r.username)}>
                    New link (kill old)
                  </button>
                  <button type="button" className="text-xs text-rt-green hover:underline"
                    onClick={() => clearFlag.mutate(r.username)}>
                    Mark reviewed
                  </button>
                </div>
              </div>
              <PayoutHistory adminKey={adminKey} username={r.username} />
            </div>
          ))}
        </section>
      )}

      <PayoutLinkGenerator adminKey={adminKey} onIssued={refresh} />

      <section className="space-y-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search @handle"
          className="w-full max-w-xs rounded-md border border-white/10 bg-rt-bg-black px-3 py-2 text-sm text-rt-fg"
        />
        <div className="overflow-x-auto rounded-xl border border-white/8">
          <table className="w-full text-sm">
            <thead className="bg-rt-bg-raised text-left text-xs uppercase tracking-wider text-rt-fg-tertiary">
              <tr>
                <th className="px-4 py-2">Creator</th>
                <th className="px-4 py-2">Method</th>
                <th className="px-4 py-2">Destination</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Updated</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const st = statusOf(r)
                return (
                  <tr key={r.username} className="border-t border-white/5 align-top">
                    <td className="px-4 py-2 text-rt-fg">@{r.handle}</td>
                    <td className="px-4 py-2 text-rt-fg-secondary">{METHOD_LABEL[r.method] ?? "—"}</td>
                    <td className="px-4 py-2 text-rt-fg-secondary font-mono text-xs">{r.destination || "—"}</td>
                    <td className={`px-4 py-2 ${st.cls}`}>{st.label}</td>
                    <td className="px-4 py-2 text-rt-fg-tertiary text-xs">
                      {r.updated_at ? new Date(r.updated_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button type="button" className="text-xs text-rt-magenta hover:underline"
                        onClick={() => setOpenHistory(openHistory === r.username ? null : r.username)}>
                        {openHistory === r.username ? "Hide" : "History"}
                      </button>
                      {openHistory === r.username && (
                        <div className="text-left mt-2 min-w-[280px]">
                          <PayoutHistory adminKey={adminKey} username={r.username} />
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
