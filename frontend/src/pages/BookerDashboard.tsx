import { useParams, useNavigate } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { useBookerStats } from "@/lib/queries"

/* BookerDashboard (CAMP-34) — one booker's roster: totals, per-label split,
   top accounts. Consumes /api/internal/bookers/<slug>/stats. */

function fmt(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${Math.round(v / 1_000)}K`
  return `${v}`
}

const LABEL_COLOR: Record<string, string> = {
  WARNER: "text-rt-magenta",
  ATLANTIC: "text-rt-purple",
  INTERNAL: "text-rt-fg-secondary",
  UNLABELED: "text-rt-fg-tertiary",
}

export default function BookerDashboard() {
  const { slug = "" } = useParams()
  const navigate = useNavigate()
  const { data, isLoading, isError, error } = useBookerStats(slug)

  if (isLoading) {
    return <div className="p-10 text-center text-sm text-rt-fg-tertiary">Loading roster…</div>
  }
  if (isError || !data) {
    return (
      <div className="p-10">
        <div className="mx-auto max-w-md rounded-xl border border-rt-red/30 bg-rt-red/10 px-4 py-4 text-center">
          <div className="text-[14px] font-medium text-rt-red">Couldn't load this booker</div>
          <div className="mt-1 text-[12px] text-rt-fg-tertiary">
            {error instanceof Error ? error.message : "No pages found for this booker."}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="relative min-h-screen rt-grain">
      <div className="relative z-10 mx-auto max-w-[1000px] px-6 py-10">
        <button
          onClick={() => navigate("/rt-tracker")}
          className="mb-5 flex items-center gap-1.5 text-[12px] text-rt-fg-tertiary hover:text-rt-fg"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Rising Tides Tracker
        </button>

        <header className="mb-8">
          <div className="text-[11px] uppercase tracking-[0.2em] text-rt-fg-tertiary">Booker Roster</div>
          <h1 className="mt-1 font-display text-4xl font-bold">
            <span className="rt-gradient-text">{data.booker}</span>
          </h1>
        </header>

        {/* Totals */}
        <section className="mb-8 grid grid-cols-4 gap-4">
          <Stat label="Total Views" value={fmt(data.total_views)} hero />
          <Stat label="Posts" value={data.post_count.toLocaleString()} />
          <Stat label="Accounts" value={`${data.account_count}`} />
          <Stat label="With Videos" value={`${data.accounts_with_videos}`} />
        </section>

        {/* Per-label split */}
        {data.by_label.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-3 text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">By Label</h2>
            <div className="flex flex-wrap gap-3">
              {data.by_label.map((l) => (
                <div key={l.label} className="rounded-xl border border-white/8 bg-rt-bg-card/50 px-4 py-3">
                  <span className={`text-[11px] uppercase tracking-wide ${LABEL_COLOR[l.label] ?? "text-rt-fg-tertiary"}`}>{l.label}</span>
                  <div className="rt-num text-lg font-bold text-rt-fg">{fmt(l.views)}</div>
                  <div className="text-[11px] text-rt-fg-tertiary">{l.posts} posts</div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Top accounts */}
        <section>
          <h2 className="mb-3 text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">Top Accounts</h2>
          <div className="overflow-hidden rounded-2xl border border-white/8">
            <div className="grid grid-cols-[1fr_5rem_5rem_4rem] gap-3 border-b border-white/8 px-5 py-2.5 text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary">
              <span>Account</span>
              <span className="text-right">Views</span>
              <span className="text-right">Label</span>
              <span className="text-right">Posts</span>
            </div>
            {data.top_accounts.map((a, i) => (
              <div
                key={a.account}
                style={{ animationDelay: `${Math.min(i * 18, 400)}ms` }}
                className="rt-rise grid grid-cols-[1fr_5rem_5rem_4rem] items-center gap-3 border-b border-white/5 px-5 py-2.5 last:border-0"
              >
                <span className="truncate text-sm font-medium text-rt-fg">@{a.account}</span>
                <span className="rt-num text-right text-sm text-rt-fg">{fmt(a.views)}</span>
                <span className={`text-right text-[11px] uppercase ${LABEL_COLOR[a.label] ?? "text-rt-fg-tertiary"}`}>{a.label}</span>
                <span className="rt-num text-right text-sm text-rt-fg-secondary">{a.posts}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function Stat({ label, value, hero }: { label: string; value: string; hero?: boolean }) {
  return (
    <div className="rounded-xl border border-white/8 bg-rt-bg-card/50 px-4 py-4">
      <div className="text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary">{label}</div>
      <div className={`rt-num mt-1 text-2xl font-bold ${hero ? "rt-gradient-text" : "text-rt-fg"}`}>{value}</div>
    </div>
  )
}
