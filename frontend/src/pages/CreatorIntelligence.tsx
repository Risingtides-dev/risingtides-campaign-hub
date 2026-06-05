import { useMemo, useState } from "react"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  Tooltip as RTooltip,
} from "recharts"
import { Search, Zap, TrendingUp, Layers, Radio, X } from "lucide-react"
import { useBreakers, useCreatorIntel } from "@/lib/queries"
import type { BreakerLens, BreakerRow, SoundTiming } from "@/lib/types"

/* ============================================================
   CREATOR INTELLIGENCE — "Mission Control for Sound Warfare"
   Who breaks sounds. Velocity over follower vanity.
   ============================================================ */

const LENSES: { id: BreakerLens; label: string; blurb: string; icon: typeof Zap }[] = [
  { id: "ceiling", label: "Ceiling", blurb: "Highest breakout odds", icon: Zap },
  { id: "volume", label: "Volume", blurb: "Proven at scale", icon: Layers },
  { id: "balanced", label: "Balanced", blurb: "Confidence-weighted", icon: TrendingUp },
]

function fmtViews(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${Math.round(v / 1_000)}K`
  return `${v}`
}

const TIMING_STYLE: Record<SoundTiming, { label: string; cls: string }> = {
  scout: { label: "⚡ SCOUT", cls: "text-rt-magenta border-rt-magenta/40 bg-rt-magenta/10" },
  early: { label: "⚡ early", cls: "text-rt-green border-rt-green/40 bg-rt-green/10" },
  mid: { label: "· mid", cls: "text-rt-fg-tertiary border-white/10 bg-white/5" },
  late: { label: "late", cls: "text-rt-amber border-rt-amber/30 bg-rt-amber/5" },
  unknown: { label: "—", cls: "text-rt-fg-tertiary border-white/5 bg-transparent" },
}

function scoreFor(row: BreakerRow, lens: BreakerLens): number {
  return lens === "ceiling" ? row.score_ceiling : lens === "volume" ? row.score_volume : row.score_balanced
}

export default function CreatorIntelligence() {
  const [lens, setLens] = useState<BreakerLens>("balanced")
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<string | null>(null)
  const { data, isLoading } = useBreakers(lens)

  const rows = useMemo(() => {
    const list = data?.breakers ?? []
    if (!query.trim()) return list
    const q = query.toLowerCase()
    return list.filter((r) => r.account.toLowerCase().includes(q))
  }, [data, query])

  const maxScore = rows.length ? Math.max(...rows.map((r) => scoreFor(r, lens))) : 1

  return (
    <div className="relative min-h-screen rt-grain">
      {/* Atmospheric backdrop */}
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background:
            "radial-gradient(800px 400px at 15% -5%, rgba(225,0,195,0.10), transparent 60%), radial-gradient(700px 500px at 95% 0%, rgba(133,0,215,0.10), transparent 55%)",
        }}
      />

      <div className="relative z-10 mx-auto max-w-[1200px] px-6 py-10">
        {/* ---- Header ---- */}
        <header className="mb-8">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-rt-fg-tertiary">
            <Radio className="h-3 w-3 text-rt-magenta rt-pulse" />
            Creator Intelligence
          </div>
          <h1 className="mt-2 font-display text-4xl font-bold leading-none">
            Who <span className="rt-gradient-text">Breaks Sounds</span>
          </h1>
          <p className="mt-2 max-w-xl text-sm text-rt-fg-secondary">
            Ranked by velocity per post, not follower vanity. The lens decides what
            "best" means — breakout odds, proven scale, or a confidence-weighted blend.
          </p>
        </header>

        {/* ---- Lens toggle + search ---- */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div className="inline-flex rounded-xl border border-white/8 bg-rt-bg-raised p-1">
            {LENSES.map((l) => {
              const Icon = l.icon
              const active = lens === l.id
              return (
                <button
                  key={l.id}
                  onClick={() => setLens(l.id)}
                  className={`group relative flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200 ${
                    active ? "text-white" : "text-rt-fg-tertiary hover:text-rt-fg-secondary"
                  }`}
                >
                  {active && (
                    <span className="absolute inset-0 rounded-lg rt-gradient-bg opacity-90" />
                  )}
                  <Icon className="relative z-10 h-4 w-4" />
                  <span className="relative z-10">{l.label}</span>
                </button>
              )
            })}
          </div>

          <div className="text-right">
            <div className="text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">
              {LENSES.find((l) => l.id === lens)?.blurb}
            </div>
            <div className="mt-1 flex items-center gap-2 rounded-lg border border-white/8 bg-rt-bg-raised px-3 py-1.5">
              <Search className="h-3.5 w-3.5 text-rt-fg-tertiary" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Find creator…"
                className="w-40 bg-transparent text-sm text-rt-fg outline-none placeholder:text-rt-fg-tertiary"
              />
            </div>
          </div>
        </div>

        {/* ---- Leaderboard ---- */}
        <div className="overflow-hidden rounded-2xl border border-white/8 bg-rt-bg-raised/60 backdrop-blur">
          <div className="grid grid-cols-[2.5rem_1fr_5rem_4.5rem_5rem_3.5rem_4rem] gap-3 border-b border-white/8 px-5 py-3 text-[10px] uppercase tracking-[0.16em] text-rt-fg-tertiary">
            <span>#</span>
            <span>Creator</span>
            <span className="text-right">Breaker</span>
            <span className="text-right">Viral</span>
            <span className="text-right">Avg</span>
            <span className="text-right">1M+</span>
            <span className="text-right">Sounds</span>
          </div>

          {isLoading && (
            <div className="px-5 py-16 text-center text-sm text-rt-fg-tertiary">
              Reading the signal…
            </div>
          )}

          {!isLoading && rows.length === 0 && (
            <div className="px-5 py-16 text-center text-sm text-rt-fg-tertiary">
              No creators match.
            </div>
          )}

          {!isLoading &&
            rows.map((row, i) => {
              const score = scoreFor(row, lens)
              const heat = Math.max(6, (score / maxScore) * 100)
              return (
                <button
                  key={row.account}
                  onClick={() => setSelected(row.account)}
                  style={{ animationDelay: `${Math.min(i * 22, 600)}ms` }}
                  className="rt-rise grid w-full grid-cols-[2.5rem_1fr_5rem_4.5rem_5rem_3.5rem_4rem] items-center gap-3 border-b border-white/5 px-5 py-3 text-left transition-colors duration-150 hover:bg-white/[0.03]"
                >
                  <span className="rt-num text-sm text-rt-fg-tertiary">{i + 1}</span>

                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-rt-fg">{row.account}</div>
                    <div className="mt-1 h-1 w-full max-w-[180px] overflow-hidden rounded-full bg-white/5">
                      <div className="h-full rt-heat" style={{ width: `${heat}%` }} />
                    </div>
                  </div>

                  <span className="rt-num text-right text-sm font-semibold text-rt-fg">
                    {score.toFixed(0)}
                  </span>
                  <span
                    className={`rt-num text-right text-sm ${
                      row.viral_rate >= 25 ? "text-rt-magenta" : row.viral_rate >= 10 ? "text-rt-green" : "text-rt-fg-secondary"
                    }`}
                  >
                    {row.viral_rate}%
                  </span>
                  <span className="rt-num text-right text-sm text-rt-fg-secondary">
                    {fmtViews(row.avg_views)}
                  </span>
                  <span className="rt-num text-right text-sm text-rt-fg-secondary">
                    {row.millionaires || "–"}
                  </span>
                  <span className="rt-num text-right text-sm text-rt-fg-tertiary">
                    {row.distinct_sounds}
                  </span>
                </button>
              )
            })}
        </div>

        <p className="mt-4 text-center text-[11px] text-rt-fg-tertiary">
          {data?.count ?? 0} creators · min {data?.min_posts ?? 5} tracked posts · click any row to drill in
        </p>
      </div>

      {selected && (
        <CreatorDrawer account={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

/* ============================================================
   DRILLDOWN DRAWER
   ============================================================ */
function CreatorDrawer({ account, onClose }: { account: string; onClose: () => void }) {
  const { data, isLoading } = useCreatorIntel(account)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <aside className="rt-rise relative h-full w-full max-w-xl overflow-y-auto border-l border-white/10 bg-rt-bg-elevated shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/8 bg-rt-bg-elevated/95 px-6 py-4 backdrop-blur">
          <div>
            <div className="text-[11px] uppercase tracking-[0.2em] text-rt-fg-tertiary">
              Sound-breaking dossier
            </div>
            <h2 className="font-display text-2xl font-bold text-rt-fg">{account}</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg border border-white/10 p-2 text-rt-fg-tertiary transition-colors hover:bg-white/5 hover:text-rt-fg"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {isLoading && (
          <div className="px-6 py-20 text-center text-sm text-rt-fg-tertiary">Loading dossier…</div>
        )}

        {data && (
          <div className="px-6 py-6">
            {/* Stat band */}
            <div className="grid grid-cols-4 gap-3">
              <Stat label="Posts" value={`${data.posts}`} />
              <Stat label="Viral rate" value={`${data.viral_rate}%`} accent={data.viral_rate >= 25} />
              <Stat label="Early/scout" value={`${data.early_adopter_rate}%`} accent={data.early_adopter_rate >= 40} />
              <Stat label="Peak" value={fmtViews(data.peak_views)} />
            </div>

            {/* Velocity distribution */}
            <section className="mt-7">
              <SectionLabel>Velocity distribution</SectionLabel>
              <div className="mt-3 h-28 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.view_distribution}>
                    <XAxis
                      dataKey="band"
                      tick={{ fill: "#909098", fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <RTooltip
                      cursor={{ fill: "rgba(255,255,255,0.04)" }}
                      contentStyle={{
                        background: "#0A0A0A",
                        border: "1px solid rgba(255,255,255,0.1)",
                        borderRadius: 12,
                        fontSize: 12,
                      }}
                      labelStyle={{ color: "#FAFCFF" }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {data.view_distribution.map((b, i) => (
                        <Cell
                          key={b.band}
                          fill={i >= 4 ? "#E100C3" : i === 3 ? "#8500D7" : "#2E323C"}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>

            {/* Sounds broken */}
            <section className="mt-7">
              <SectionLabel>Sounds broken · {data.distinct_sounds}</SectionLabel>
              <div className="mt-3 space-y-2">
                {data.sounds.slice(0, 12).map((s) => {
                  const t = TIMING_STYLE[s.timing]
                  return (
                    <div
                      key={s.sound_id + s.campaign_slug}
                      className="flex items-center gap-3 rounded-xl border border-white/6 bg-rt-bg-card/60 px-4 py-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-rt-fg">
                          {s.sound_title || s.sound_id}
                        </div>
                        <div className="truncate text-xs text-rt-fg-tertiary">
                          {s.artist || "—"} · {s.posts} post{s.posts !== 1 ? "s" : ""}
                        </div>
                      </div>
                      <span className="rt-num text-sm font-semibold text-rt-fg">
                        {fmtViews(s.peak_views)}
                      </span>
                      <span
                        className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${t.cls}`}
                        title={
                          s.days_after_start != null
                            ? `posted ${s.days_after_start} days after campaign start`
                            : "timing unknown"
                        }
                      >
                        {t.label}
                      </span>
                    </div>
                  )
                })}
              </div>
            </section>
          </div>
        )}
      </aside>
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-white/6 bg-rt-bg-card/50 px-3 py-3">
      <div className="text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary">{label}</div>
      <div className={`rt-num mt-1 text-lg font-semibold ${accent ? "rt-gradient-text" : "text-rt-fg"}`}>
        {value}
      </div>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">{children}</div>
  )
}
