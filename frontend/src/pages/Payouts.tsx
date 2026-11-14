// Hub admin page for creator payout details. Gated by PAYOUT_ADMIN_KEY
// because the Hub itself has no login. Changed destinations are flagged at
// the top until reviewed — the dashboard flag is the change alert.
import { useEffect, useMemo, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { PAYOUT_METHODS, payoutAdmin } from "@/lib/payouts"
import type { PayoutAdminRow } from "@/lib/payouts"
import { PayoutHistory } from "@/components/payouts/PayoutHistory"
import { PayoutLinkGenerator } from "@/components/payouts/PayoutLinkGenerator"
import { CampaignPayouts } from "@/components/payouts/CampaignPayouts"
import { PayoutBatches } from "@/components/payouts/PayoutBatches"
import { PayoutSessionProvider } from "@/lib/payoutSession"

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
        aria-label="Payout admin key"
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
  const [session, setSession] = useState<{ key: string; id: string } | null>(() => {
    const key = sessionStorage.getItem(KEY_STORAGE)
    return key ? { key, id: crypto.randomUUID() } : null
  })
  const sessionRef = useRef(session)
  const mounted = useRef(true)
  const adminKey = session?.key ?? ""
  const prefix = ["payouts", session?.id ?? "locked"] as const
  const [search, setSearch] = useState("")
  const [openHistory, setOpenHistory] = useState<string | null>(null)
  const [tab, setTab] = useState<"pay" | "info">("pay")
  const [rotatedLink, setRotatedLink] = useState<{ username: string; link: string } | null>(null)
  const qc = useQueryClient()

  function isSessionActive(id: string) {
    return mounted.current && sessionRef.current?.id === id
  }

  function clearPayoutCache() {
    void qc.cancelQueries({ queryKey: ["payouts"] })
    qc.removeQueries({ queryKey: ["payouts"] })
    for (const mutation of qc.getMutationCache().findAll({ mutationKey: ["payouts"] })) {
      qc.getMutationCache().remove(mutation)
    }
  }

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      const id = sessionRef.current?.id
      if (!id) return
      void qc.cancelQueries({ queryKey: ["payouts", id] })
      qc.removeQueries({ queryKey: ["payouts", id] })
      for (const mutation of qc.getMutationCache().findAll({ mutationKey: ["payouts", id] })) {
        qc.getMutationCache().remove(mutation)
      }
    }
  }, [qc])

  const overview = useQuery({
    queryKey: [...prefix, "overview"],
    queryFn: async ({ signal }) => {
      if (!session || signal.aborted || !isSessionActive(session.id)) throw new Error("Payouts are locked")
      const data = await payoutAdmin.overview(session.key)
      if (signal.aborted || !isSessionActive(session.id)) throw new Error("Payout session closed")
      return data
    },
    enabled: Boolean(session),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
  })

  const forgetKey = () => {
    sessionRef.current = null
    sessionStorage.removeItem(KEY_STORAGE)
    setSession(null)
    setSearch("")
    setOpenHistory(null)
    setTab("pay")
    setRotatedLink(null)
    clearPayoutCache()
    clearFlag.reset()
    rotate.reset()
  }
  const saveKey = (key: string) => {
    clearPayoutCache()
    const next = { key, id: crypto.randomUUID() }
    sessionRef.current = next
    sessionStorage.setItem(KEY_STORAGE, key)
    setSession(next)
  }

  const refresh = () => {
    if (session && isSessionActive(session.id)) void qc.invalidateQueries({ queryKey: prefix })
  }
  type CreatorAction = { username: string; sessionId: string }
  const onError = (error: unknown, variables: CreatorAction) => {
    if (isSessionActive(variables.sessionId)) toast.error(error instanceof Error ? error.message : "Request failed")
  }
  const actionKey = (variables: CreatorAction) => {
    const active = sessionRef.current
    if (!active || !isSessionActive(variables.sessionId)) throw new Error("Payout session closed")
    return active.key
  }

  const clearFlag = useMutation({
    mutationKey: [...prefix, "clear-flag"],
    retry: false,
    mutationFn: (variables: CreatorAction) => payoutAdmin.clearFlag(actionKey(variables), variables.username),
    onSuccess: (_res, variables) => {
      if (!isSessionActive(variables.sessionId)) return
      toast.success("Marked reviewed")
      refresh()
    },
    onError,
  })
  const rotate = useMutation({
    mutationKey: [...prefix, "rotate-link"],
    retry: false,
    mutationFn: (variables: CreatorAction) => payoutAdmin.rotate(actionKey(variables), variables.username),
    onMutate: () => setRotatedLink(null),
    onSuccess: async (res, variables) => {
      if (!isSessionActive(variables.sessionId)) return
      setRotatedLink({ username: res.username, link: res.link })
      try {
        await navigator.clipboard.writeText(res.link)
        if (isSessionActive(variables.sessionId)) toast.success(`New link for @${res.username} copied`)
      } catch {
        if (isSessionActive(variables.sessionId)) toast.error("New link created. Clipboard unavailable — copy the link below.")
      }
      if (isSessionActive(variables.sessionId)) refresh()
    },
    onError,
  })

  const rows = useMemo(() => {
    const all = overview.data?.creators ?? []
    const q = search.trim().toLowerCase().replace(/^@/, "")
    return q ? all.filter((r) => r.username.includes(q)) : all
  }, [overview.data, search])

  if (!session) return <div className="p-6"><KeyGate onKey={saveKey} /></div>

  if (!overview.isSuccess || !overview.data) {
    return (
      <div className="p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold font-display text-rt-fg">Payouts</h1>
          <button type="button" onClick={forgetKey} className="text-xs text-rt-fg-tertiary hover:text-rt-fg">Lock</button>
        </div>
        {overview.error ? <>
          <p role="alert" className="text-sm text-rt-red">{overview.error.message}</p>
          <button type="button" onClick={() => void overview.refetch()} className="text-sm text-rt-magenta hover:underline">Retry</button>
        </> : <p className="text-sm text-rt-fg-tertiary">Checking access…</p>}
      </div>
    )
  }

  const s = overview.data?.summary
  const flagged = rows.filter((r) => r.flagged)

  return (
    <PayoutSessionProvider sessionId={session.id} isActive={() => isSessionActive(session.id)}>
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold font-display text-rt-fg">Payouts</h1>
        <button type="button" onClick={forgetKey} className="text-xs text-rt-fg-tertiary hover:text-rt-fg">
          Lock
        </button>
      </div>


      <div className="flex gap-1 border-b border-white/8">
        {([["pay", "Pay creators"], ["info", "Payment info"]] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm -mb-px border-b-2 ${tab === key ? "border-rt-magenta text-rt-fg font-semibold" : "border-transparent text-rt-fg-tertiary hover:text-rt-fg"}`}
          >
            {label}
            {key === "info" && s && s.flagged > 0 && (
              <span className="ml-2 rounded-full bg-rt-red px-1.5 text-[11px] text-white">{s.flagged}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "pay" && s && s.flagged > 0 && (
        <button type="button" onClick={() => setTab("info")}
          className="w-full rounded-lg border border-rt-red/40 bg-rt-red/5 px-4 py-2 text-left text-sm text-rt-red">
          {s.flagged} creator{s.flagged === 1 ? "" : "s"} changed their payment info — review on the Payment info tab before paying them →
        </button>
      )}

      {tab === "pay" && s && <PayoutBatches adminKey={adminKey} />}
      {tab === "pay" && s && <CampaignPayouts adminKey={adminKey} />}

      {tab === "info" && s && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Tile label="Confirmed by creator" value={s.confirmed} tone="text-rt-green" />
          <Tile label="On file, unconfirmed" value={s.unconfirmed_on_file} tone="text-rt-amber" />
          <Tile label="Missing" value={s.missing} />
          <Tile label="Changed — needs review" value={s.flagged} tone={s.flagged ? "text-rt-red" : "text-rt-fg"} />
          <Tile label="Links issued" value={s.links_issued} />
        </div>
      )}

      {tab === "info" && flagged.length > 0 && (
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
                    disabled={rotate.isPending}
                    onClick={() => rotate.mutate({ username: r.username, sessionId: session.id })}>
                    New link (kill old)
                  </button>
                  <button type="button" className="text-xs text-rt-green hover:underline"
                    onClick={() => clearFlag.mutate({ username: r.username, sessionId: session.id })}>
                    Mark reviewed
                  </button>
                </div>
              </div>
              <PayoutHistory adminKey={adminKey} username={r.username} />
            </div>
          ))}
        </section>
      )}

      {tab === "info" && rotatedLink && (
        <div className="space-y-2">
          <p className="text-sm text-rt-fg">New link for @{rotatedLink.username}</p>
          <input aria-label={`New payment-info link for @${rotatedLink.username}`} readOnly value={rotatedLink.link}
            onFocus={(event) => event.currentTarget.select()}
            className="w-full rounded-md border border-white/10 bg-rt-bg-black px-3 py-2 text-xs text-rt-fg" />
        </div>
      )}

      {tab === "info" && <PayoutLinkGenerator adminKey={adminKey} onIssued={refresh} />}

      {tab === "info" && <section className="space-y-3">
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
      </section>}
    </div>
    </PayoutSessionProvider>
  )
}
