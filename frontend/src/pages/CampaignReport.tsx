import { useParams } from "react-router-dom"
import { Printer, ExternalLink } from "lucide-react"
import { useCampaignReport } from "@/lib/queries"

/* ============================================================
   CLIENT CAMPAIGN REPORT (CAMP-84)
   Shareable performance summary — reach + sound-spread, no financials.
   Print-styled (Cmd+P → PDF) for handing to labels.
   ============================================================ */

function fmt(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${Math.round(v / 1_000)}K`
  return `${v}`
}
function fmtFull(v: number): string {
  return v.toLocaleString("en-US")
}

export default function CampaignReport() {
  const { slug = "" } = useParams()
  const { data, isLoading, isError, error } = useCampaignReport(slug)

  if (isLoading) {
    return <div className="p-10 text-center text-sm text-rt-fg-tertiary">Building report…</div>
  }
  if (isError || !data) {
    return (
      <div className="p-10">
        <div className="mx-auto max-w-md rounded-xl border border-rt-red/30 bg-rt-red/10 px-4 py-4 text-center">
          <div className="text-[14px] font-medium text-rt-red">Couldn't build report</div>
          <div className="mt-1 text-[12px] text-rt-fg-tertiary">
            {error instanceof Error ? error.message : "Campaign not found or the request failed."}
          </div>
        </div>
      </div>
    )
  }

  const h = data.headline
  const stale = data.source.includes("cached") || data.source.includes("fallback")

  return (
    <div className="mx-auto max-w-[900px] px-6 py-8 print:px-0 print:py-0">
      {/* Toolbar (hidden on print) */}
      <div className="mb-6 flex items-center justify-between print:hidden">
        <div className="text-[11px] uppercase tracking-[0.22em] text-rt-fg-tertiary">
          Campaign Report
        </div>
        <button
          onClick={() => window.print()}
          className="flex items-center gap-2 rounded-lg rt-gradient-bg px-4 py-2 text-sm font-medium text-white"
        >
          <Printer className="h-4 w-4" />
          Print / Save PDF
        </button>
      </div>

      {/* Report header */}
      <header className="mb-8 border-b border-white/8 pb-6 print:border-black/10">
        <h1 className="font-display text-4xl font-bold leading-tight text-rt-fg print:text-black">
          {data.song || data.title}
        </h1>
        <div className="mt-1 text-lg text-rt-fg-secondary print:text-neutral-600">
          {data.artist}
        </div>
        <div className="mt-2 flex items-center gap-3 text-xs text-rt-fg-tertiary">
          {data.start_date && <span>Started {data.start_date}</span>}
          {stale && (
            <span className="rounded border border-rt-amber/30 bg-rt-amber/10 px-2 py-0.5 text-rt-amber">
              cached data
            </span>
          )}
        </div>
      </header>

      {/* Headline metrics */}
      <section className="mb-8 grid grid-cols-4 gap-4">
        <HeadlineStat label="Total Views" value={fmt(h.total_views)} hero />
        <HeadlineStat label="Total Likes" value={fmt(h.total_likes)} />
        <HeadlineStat label="Posts" value={fmtFull(h.post_count)} />
        <HeadlineStat label="Creators" value={fmtFull(h.creator_count)} />
      </section>

      {/* Top posts */}
      {data.top_posts.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">
            Top Performing Posts
          </h2>
          <div className="overflow-hidden rounded-xl border border-white/8 print:border-black/10">
            {data.top_posts.map((p, i) => (
              <div
                key={p.url + i}
                className="grid grid-cols-[2rem_2.5rem_1fr_5rem_5rem_2rem] items-center gap-3 border-b border-white/5 px-4 py-2.5 last:border-0 print:border-black/5"
              >
                <span className="rt-num text-sm text-rt-fg-tertiary">{i + 1}</span>
                {/* CAMP-76: post thumbnail (cover_url), served live from Cobrand */}
                {p.cover_url ? (
                  <img
                    src={p.cover_url}
                    alt=""
                    className="h-10 w-8 shrink-0 rounded object-cover border border-white/10"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden" }}
                  />
                ) : (
                  <div className="h-10 w-8 shrink-0 rounded bg-white/5 border border-white/8" />
                )}
                <span className="truncate text-sm font-medium text-rt-fg print:text-black">{p.account}</span>
                <span className="rt-num text-right text-sm font-semibold text-rt-fg print:text-black">{fmt(p.views)}</span>
                <span className="rt-num text-right text-xs text-rt-fg-tertiary">{fmt(p.likes)} likes</span>
                <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-rt-fg-tertiary hover:text-rt-magenta print:hidden">
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Per-creator delivery */}
      <section>
        <h2 className="mb-3 text-[11px] uppercase tracking-[0.18em] text-rt-fg-tertiary">
          Creator Delivery
        </h2>
        <div className="overflow-hidden rounded-xl border border-white/8 print:border-black/10">
          <div className="grid grid-cols-[1fr_4rem_5rem_5rem_5rem] gap-3 border-b border-white/8 px-4 py-2.5 text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary print:border-black/10">
            <span>Creator</span>
            <span className="text-right">Posts</span>
            <span className="text-right">Views</span>
            <span className="text-right">Shares</span>
            <span className="text-right">Comments</span>
          </div>
          {data.creators.map((c) => (
            <div
              key={c.username}
              className="grid grid-cols-[1fr_4rem_5rem_5rem_5rem] gap-3 border-b border-white/5 px-4 py-2.5 last:border-0 print:border-black/5"
            >
              <span className="truncate text-sm font-medium text-rt-fg print:text-black">@{c.username}</span>
              <span className="rt-num text-right text-sm text-rt-fg-secondary">{c.posts}</span>
              <span className="rt-num text-right text-sm text-rt-fg print:text-black">{fmt(c.views)}</span>
              <span className={`rt-num text-right text-sm ${c.shares > 0 ? "font-semibold text-rt-magenta" : "text-rt-fg-tertiary"}`}>
                {c.shares > 0 ? fmt(c.shares) : "—"}
              </span>
              <span className="rt-num text-right text-sm text-rt-fg-secondary">{c.comments > 0 ? fmt(c.comments) : "—"}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-rt-fg-tertiary">
          Shares drive sound spread — the signal that compounds a track's reach beyond the post itself.
        </p>
      </section>
    </div>
  )
}

function HeadlineStat({ label, value, hero }: { label: string; value: string; hero?: boolean }) {
  return (
    <div className="rounded-xl border border-white/8 bg-rt-bg-card/50 px-4 py-4 print:border-black/10 print:bg-transparent">
      <div className="text-[10px] uppercase tracking-[0.14em] text-rt-fg-tertiary">{label}</div>
      <div className={`rt-num mt-1 text-2xl font-bold ${hero ? "rt-gradient-text print:text-black" : "text-rt-fg print:text-black"}`}>
        {value}
      </div>
    </div>
  )
}
