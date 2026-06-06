import { useNavigate } from "react-router-dom"
import { Radio, Building2, Users } from "lucide-react"
import { useLabelStats, useBookers } from "@/lib/queries"

/* ============================================================
   RISING TIDES TRACKER (CAMP-34)
   Leadership landing — both attribution axes in one view:
   label totals (Warner/Atlantic/Internal) + the booker leaderboard.
   Consumes /api/internal/labels + /api/internal/bookers.
   ============================================================ */

function fmt(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${Math.round(v / 1_000)}K`
  return `${v}`
}

const LABEL_ACCENT: Record<string, string> = {
  WARNER: "from-rt-magenta/15 to-rt-purple/10 border-rt-magenta/25",
  ATLANTIC: "from-rt-purple/15 to-rt-magenta/10 border-rt-purple/25",
  INTERNAL: "from-white/8 to-white/4 border-white/12",
}

export default function RisingTidesTracker() {
  const navigate = useNavigate()
  const labels = useLabelStats()
  const bookers = useBookers()

  const labelRows = labels.data?.labels ?? []
  const bookerRows = bookers.data?.bookers ?? []
  const maxBooker = bookerRows.length ? Math.max(...bookerRows.map((b) => b.total_views)) : 1
  const grandTotal = labelRows.reduce((s, l) => s + l.total_views, 0)

  return (
    <div className="relative min-h-screen rt-grain">
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background:
            "radial-gradient(900px 450px at 12% -5%, rgba(225,0,195,0.10), transparent 60%), radial-gradient(800px 520px at 92% 0%, rgba(133,0,215,0.10), transparent 55%)",
        }}
      />
      <div className="relative z-10 mx-auto max-w-[1100px] px-6 py-10">
        <header className="mb-8">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-rt-fg-tertiary">
            <Radio className="h-3 w-3 text-rt-magenta rt-pulse" />
            Rising Tides Tracker
          </div>
          <h1 className="mt-2 font-display text-4xl font-bold leading-none">
            The <span className="rt-gradient-text">Whole Operation</span>
          </h1>
          <p className="mt-2 max-w-xl text-sm text-rt-fg-secondary">
            Every internal page's reach, attributed two ways — by label and by booker.
            Sourced from Notion, no cross-contamination.
          </p>
        </header>

        {/* Label hero cards */}
        <section className="mb-10">
          <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">
            <Building2 className="h-3.5 w-3.5" /> By Label
          </div>
          {labels.isLoading ? (
            <div className="py-10 text-center text-sm text-rt-fg-tertiary">Loading labels…</div>
          ) : labels.isError ? (
            <div className="rounded-xl border border-rt-red/30 bg-rt-red/10 px-4 py-4 text-center text-sm text-rt-red">
              Couldn't load label attribution.
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4">
              {labelRows.map((l, i) => {
                const pct = grandTotal ? Math.round((l.total_views / grandTotal) * 100) : 0
                return (
                  <div
                    key={l.slug}
                    style={{ animationDelay: `${Math.min(i * 60, 300)}ms` }}
                    className={`rt-rise rounded-2xl border bg-gradient-to-br ${LABEL_ACCENT[l.label] ?? "border-white/10 from-white/5 to-white/0"} p-5`}
                  >
                    <div className="text-[11px] uppercase tracking-[0.16em] text-rt-fg-tertiary">{l.label}</div>
                    <div className="rt-num mt-1 font-display text-3xl font-bold rt-gradient-text">{fmt(l.total_views)}</div>
                    <div className="mt-2 flex items-center justify-between text-[12px] text-rt-fg-secondary">
                      <span>{l.account_count} accounts</span>
                      <span>{pct}% of total</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        {/* Booker leaderboard */}
        <section>
          <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">
            <Users className="h-3.5 w-3.5" /> By Booker
          </div>
          {bookers.isLoading ? (
            <div className="py-10 text-center text-sm text-rt-fg-tertiary">Loading bookers…</div>
          ) : bookers.isError ? (
            <div className="rounded-xl border border-rt-red/30 bg-rt-red/10 px-4 py-4 text-center text-sm text-rt-red">
              Couldn't load booker attribution.
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-white/8 bg-rt-bg-raised/60 backdrop-blur">
              <div className="grid grid-cols-[2.5rem_1fr_5rem_4.5rem] gap-3 border-b border-white/8 px-5 py-3 text-[10px] uppercase tracking-[0.16em] text-rt-fg-tertiary">
                <span>#</span>
                <span>Booker</span>
                <span className="text-right">Views</span>
                <span className="text-right">Accounts</span>
              </div>
              {bookerRows.map((b, i) => {
                const heat = Math.max(6, (b.total_views / maxBooker) * 100)
                return (
                  <button
                    key={b.slug}
                    onClick={() => navigate(`/team/${b.slug}`)}
                    style={{ animationDelay: `${Math.min(i * 22, 400)}ms` }}
                    className="rt-rise grid w-full grid-cols-[2.5rem_1fr_5rem_4.5rem] items-center gap-3 border-b border-white/5 px-5 py-3 text-left transition-colors hover:bg-white/[0.03]"
                  >
                    <span className="rt-num text-sm text-rt-fg-tertiary">{i + 1}</span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-rt-fg">{b.booker}</div>
                      <div className="mt-1 h-1 w-full max-w-[220px] overflow-hidden rounded-full bg-white/5">
                        <div className="h-full rt-heat" style={{ width: `${heat}%` }} />
                      </div>
                    </div>
                    <span className="rt-num text-right text-sm font-semibold text-rt-fg">{fmt(b.total_views)}</span>
                    <span className="rt-num text-right text-sm text-rt-fg-secondary">{b.account_count}</span>
                  </button>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
